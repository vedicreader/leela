"""Surviving a long conversation, and saying so afterwards.

Neither rishi nor fastllm has any notion of this. Rishi even exposes `pct_full` and
`ctx_limit` and then does nothing with them. Tau does have it, and its
`context_window.py` is the cleanest thing in that codebase: a deterministic size estimate,
a threshold set a reserve below the window, a *structured* summary prompt, and -- the part
people forget -- a separate prompt for **updating** an existing summary rather than
summarising a summary until nothing is left. Those prompts are ported here.

Two things are ours.

**The summary goes in the notebook.** Everywhere else compaction is an invisible event you
discover later by noticing the agent has forgotten something. Here the summary is written
into the document as a cell: readable, editable, saved with the work, and legible in plain
Jupyter. If the model dropped something that mattered, you can type it back in.

**The reorientation note tells the truth about what survived**, which is the good idea in
aai-coding's post-compaction hooks. Its `COMPACT_MSG` works because it is specific: your
context was rewritten, but the kernel process was not, so do not re-run startup. leela is
in exactly that position and can say something even more useful, because the kernel really
is still there -- the namespace, the imports, the dataframe that took four minutes to
build. A model that has just been compacted will otherwise reload the data.

`prompt_notices` is from the same family: aai-coding's `UserPromptSubmit` hook, which
notices that a prompt ending in a question mark is a question and should be answered
before more tool calls, and that a bare "go" approves what was actually agreed and not
everything that was ever proposed. That last one earns its place next to `hitl.py`.
"""

from __future__ import annotations
import re

__all__ = ['CHARS_PER_TOKEN', 'RESERVE', 'KEEP_RECENT', 'SUMMARY_PREFIX', 'SUMMARISE_SP', 'SUMMARISE',
           'UPDATE_SUMMARISE', 'REORIENT', 'estimate_tokens', 'threshold', 'should_compact',
           'summarise_prompt', 'serialise', 'split_previous', 'reorient', 'prompt_notices', 'Compactor']

CHARS_PER_TOKEN = 4          # tau's estimate, for text no tokenizer has seen yet
RESERVE = 16_384             # headroom kept below the window: one full reply plus its tool results
KEEP_RECENT = 20_000         # tokens of recent conversation compaction does not touch
SUMMARY_PREFIX = 'Previous conversation summary:\n'

SUMMARISE_SP = ("You are a context summarization assistant. Read a conversation between a user and an AI "
                "coding assistant and produce a structured summary in exactly the format specified.\n\n"
                "Do NOT continue the conversation. Do NOT answer any question in it. Output ONLY the summary.")

_FORMAT = """## Goal
[What is the user trying to accomplish? Several items if the session covers several tasks.]

## Constraints & Preferences
- [Constraints, preferences or requirements the user stated, or "(none)"]

## Progress
### Done
- [x] [Completed tasks and changes]

### In Progress
- [ ] [Current work]

### Blocked
- [Anything preventing progress, if any]

## Key Decisions
- **[Decision]**: [Brief rationale]

## Next Steps
1. [Ordered list of what should happen next]

## Critical Context
- [Data, examples, file paths or references needed to continue, or "(none)"]

Keep each section concise. Preserve exact file paths, symbol names, error messages, and
any `lineno|hash|` addresses still needed for a pending edit."""

SUMMARISE = ("The messages above are a conversation to summarize. Write a context checkpoint another "
             f"model will use to continue the work.\n\nUse this EXACT format:\n\n{_FORMAT}")

UPDATE_SUMMARISE = ("The messages above are NEW messages to fold into the existing summary in "
                    "<previous-summary> tags.\n\nRULES:\n"
                    "- PRESERVE everything from the previous summary that is still true\n"
                    "- ADD new progress, decisions and context from the new messages\n"
                    '- MOVE items from "In Progress" to "Done" as they complete\n'
                    "- UPDATE Next Steps to reflect what was accomplished\n"
                    "- PRESERVE exact file paths, symbol names and error messages\n"
                    "- Drop anything no longer relevant\n\n"
                    f"Use this EXACT format:\n\n{_FORMAT}")


def reorient(kernel_alive=True, skills=()):
    """What the model is told immediately after its context is rewritten.

    Specific, because a vague note ("some context was lost") produces a model that either
    ignores it or re-does everything. Each clause is here because omitting it causes a
    concrete failure: without the kernel sentence the model re-imports and reloads data
    that is still in memory; without the skills sentence it works from a half-remembered
    skill it can no longer see; without the last sentence it re-answers a question it
    already answered, because the summary reads like an instruction to resume.
    """
    live = ("**Your context was rewritten to fit the window, but the kernel process was not touched.** "
            "The user's namespace, imports and variables are all still live exactly as they were -- do "
            "not re-import anything, do not rebuild data, and do not re-run setup. Call `list_vars` if "
            "you need to see what is there."
            if kernel_alive else
            "**Your context was rewritten and the kernel has restarted with a clean namespace.** "
            "Rebuild variables on demand; do not assume anything is still bound.")
    sk = (f"Skill text you read earlier is gone from your context; re-read it with `read_skill` before "
          f"relying on it ({', '.join(skills)})." if skills else
          "Any skill text you read earlier is gone from your context; re-read it before relying on it.")
    return (f'<system-reminder>\n{live}\n\n{sk}\n\n'
            'The summary above describes work in flight. If the last thing the user asked has already '
            'been answered and nothing is open, do not resume or re-answer anything -- reply with one '
            'short line and wait.\n</system-reminder>')


REORIENT = reorient()


# ---------------------------------------------------------------------------
# how big is it
# ---------------------------------------------------------------------------
def estimate_tokens(text, count=None):
    "Tokens in `text`: exact via `count` when a tokenizer is at hand, tau's chars/4 otherwise."
    if not text: return 0
    if count is not None:
        try: return count(text)
        except Exception: pass
    return max(1, (len(text) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN)


def threshold(ctx, reserve=RESERVE):
    "The token count at which a conversation should be compacted, or None when there is no window."
    if not ctx or ctx <= 0: return None
    return max(1, ctx - reserve)


def should_compact(used, ctx, reserve=RESERVE):
    "Whether `used` tokens against a `ctx` window has crossed the line."
    t = threshold(ctx, reserve)
    return bool(t and used >= t)


# ---------------------------------------------------------------------------
# what to summarise
# ---------------------------------------------------------------------------
def _text(m):
    "The readable text of a message in either backend's shape."
    if hasattr(m, 'content') and not isinstance(m, dict):        # aidialog Msg
        return '\n'.join(str(p.text) for p in m.content if getattr(p, 'text', None))
    if not isinstance(m, dict): return str(m)
    c = m.get('content', '')
    if isinstance(c, str): return c
    out = []
    for p in c or []:
        if not isinstance(p, dict): continue
        if p.get('type') == 'text': out.append(p.get('text', ''))
        elif p.get('type') == 'tool_response': out.append(f"[{p.get('name','tool')}] {p.get('response')}")
    return '\n'.join(x for x in out if x)


def _role(m):
    return getattr(m, 'role', None) or (m.get('role', '?') if isinstance(m, dict) else '?')


def _calls(m):
    "Tool call names on an assistant message, in either shape."
    tcs = getattr(m, 'tool_calls', None)
    if tcs is None and isinstance(m, dict): tcs = m.get('tool_calls')
    if not tcs:
        parts = getattr(m, 'content', None)
        if parts and not isinstance(m, dict):
            return [p.data.get('name', '?') for p in parts if getattr(p, 'type', '') == 'tool_use' and p.data]
        return []
    out = []
    for t in tcs:
        n = getattr(t, 'name', None) or (t.get('function', {}).get('name') if isinstance(t, dict) else None)
        if n: out.append(n)
    return out


def serialise(msgs, mx=2000):
    "Messages as the tagged block the summarizer reads. Tool results clipped: they are the bulk."
    if not msgs: return '(no new messages)'
    out = []
    for i, m in enumerate(msgs, 1):
        out.append(f'<message index={i} role={_role(m)}>')
        if (t := _text(m)): out.append(t[:mx] + ('…' if len(t) > mx else ''))
        if (cs := _calls(m)): out.append('<tool-calls>' + ', '.join(cs) + '</tool-calls>')
        out.append('</message>')
    return '\n'.join(out)


def split_previous(msgs):
    "`(previous_summary_or_None, remaining_msgs)` -- so an update updates rather than re-summarises."
    if not msgs: return None, msgs
    t = _text(msgs[0])
    if _role(msgs[0]) == 'user' and t.startswith(SUMMARY_PREFIX):
        return t[len(SUMMARY_PREFIX):], msgs[1:]
    return None, msgs


def summarise_prompt(msgs, extra=''):
    "The whole prompt handed to the summarizer, choosing the fresh or the updating instructions."
    prev, rest = split_previous(msgs)
    p = f'<conversation>\n{serialise(rest)}\n</conversation>\n\n'
    if prev is not None: p += f'<previous-summary>\n{prev}\n</previous-summary>\n\n'
    base = UPDATE_SUMMARISE if prev is not None else SUMMARISE
    if extra.strip(): base = f'{base}\n\nAdditional focus: {extra.strip()}'
    return p + base


# ---------------------------------------------------------------------------
# notices on the way in
# ---------------------------------------------------------------------------
Q_NOTICE = ('This prompt ends with a question mark, so it is a question. Make only the tool calls needed '
            'to answer it, then answer it, then stop -- do not start the work it implies.')
READ_NOTICE = ('This prompt asks you to read something. Read the target in full now, before composing any '
               'response: a notebook with `notebook_cells` then `view_cell`, a file with `view_file`. '
               'Never answer from assumed or remembered contents.')
APPROVAL_NOTICE = ('This bare approval covers exactly what was explicitly agreed, and nothing more. Before '
                   'acting, check that each thing you are about to do was confirmed by the user -- not '
                   'merely proposed, listed or summarised by you. If approval of an item is uncertain, it '
                   'is not approved: ask.')
BTW_NOTICE = ('This prompt begins with "BTW" and is a side request. Answer it first, then resume the '
              'previous task if it has unfinished items. It does not cancel that task.')

_APPROVALS = ('go', 'ok', 'okay', 'yes', 'yep', 'sure', 'do it', 'go ahead', 'proceed')


def prompt_notices(prompt):
    """Notices a submitted prompt earns, from aai-coding's `UserPromptSubmit` hook.

    Cheap, and each one fixes a failure people actually hit. The approval notice matters
    most in a harness that asks for approval: a person who types "go" after a long
    exchange is approving the thing under discussion, not the four other things the model
    listed on the way there.
    """
    p = (prompt or '').strip()
    out = []
    if p.endswith('?'): out.append(Q_NOTICE)
    if re.search(r'\b(please read|read the|have a look at)\b', p.lower()): out.append(READ_NOTICE)
    if re.sub(r'^\W+|[\s.!]+$', '', p.lower()) in _APPROVALS: out.append(APPROVAL_NOTICE)
    if p.lower().startswith('btw'): out.append(BTW_NOTICE)
    return out


def notices_block(prompt):
    "The notices for `prompt` as one reminder to append to it, or `''`."
    ns = prompt_notices(prompt)
    return '' if not ns else '\n\n<system-reminder>\n' + '\n\n'.join(ns) + '\n</system-reminder>'


# ---------------------------------------------------------------------------
class Compactor:
    """Decides when to compact, and does it.

    Deliberately not a callback on either engine. Compaction needs a *second* model call
    on a *different* (cheap) model, and then it has to replace the first model's history --
    which is two things neither backend's callback system is shaped for. Keeping it out
    here also means the summary is available to write into the notebook, which is the
    point.
    """

    def __init__(self,
                 reserve=RESERVE,
                 keep_recent=KEEP_RECENT,
                 auto=True,                  # compact automatically on crossing the threshold
                 kernel_alive=True,          # what the reorientation note may promise
                 on_compact=None):           # called with the summary text once it exists
        self.reserve, self.keep_recent, self.auto = reserve, keep_recent, auto
        self.kernel_alive, self.on_compact = kernel_alive, on_compact
        self.count = 0
        self.last = ''
        self.note = 'not compacted'

    def due(self, backend):
        "Whether `backend` has crossed its threshold."
        return should_compact(backend.used_tokens, backend.spec.ctx, self.reserve)

    def _keep(self, msgs, count=None):
        """The tail to keep uncompacted, newest-first until the budget runs out.

        Kept whole-message: half a tool result is worse than none, and a kept assistant
        message whose tool result was dropped leaves a dangling call that some providers
        reject outright.
        """
        kept, used = [], 0
        for m in reversed(msgs):
            n = estimate_tokens(_text(m), count) + 8
            if used + n > self.keep_recent and kept: break
            kept.append(m); used += n
        kept.reverse()
        # Then cut back to a clean boundary. A tail that starts at a tool result whose
        # assistant call was just summarised away is a dangling tool call, which some
        # providers reject outright and all of them find confusing, so the tail always
        # starts at a user turn.
        while kept and _role(kept[0]) != 'user': kept.pop(0)
        return kept

    def compact(self, backend, summariser, extra=''):
        """Summarise `backend`'s conversation and replace it. Returns the summary, or `''`.

        `summariser` is a callable taking `(prompt, sp)` and returning text -- normally
        the cheap local backend's `oneshot`. The summary is produced by one model and
        installed in another's history on purpose: it is a mechanical transformation of a
        transcript, and paying frontier prices to compress a frontier conversation is the
        exact sort of spending routing exists to stop.
        """
        msgs = list(backend.hist or [])
        if not msgs:
            self.note = 'nothing to compact'
            return ''
        keep = self._keep(msgs, backend.count_tokens)
        older = msgs[:len(msgs) - len(keep)] if len(keep) < len(msgs) else msgs
        if not older:
            self.note = 'everything is recent; nothing to compact'
            return ''
        try:
            text = (summariser(summarise_prompt(older, extra), SUMMARISE_SP) or '').strip()
        except Exception as e:
            from . import agent_err
            self.note = f'compaction failed ({agent_err(e)})'
            return ''
        if not text:
            self.note = 'the summarizer returned nothing; conversation left alone'
            return ''
        head = SUMMARY_PREFIX + text + '\n\n' + reorient(self.kernel_alive)
        try:
            backend.replace_hist(head, keep)
        except Exception as e:
            from . import agent_err
            self.note = f'compaction summary written but history not replaced ({agent_err(e)})'
            return text
        self.count += 1
        self.last = text
        self.note = f'compacted {len(older)} message(s), kept {len(keep)}'
        if self.on_compact:
            try: self.on_compact(text)
            except Exception: pass
        return text
