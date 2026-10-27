let lessonDueRows = null, lessonDueError = '', lessonDueSeq = 0;
function paintLessonReview() {
  const body = $('#lessonreviewbody'); if (!body) return;
  body.replaceChildren();
  if (lessonDueError) {
    const message = document.createElement('p'); message.textContent = lessonDueError;
    const retry = document.createElement('button'); retry.type = 'button'; retry.className = 'lee-btn'; retry.textContent = 'Try again';
    retry.onclick = refreshLessonDue; body.append(message, retry); return;
  }
  if (lessonDueRows === null) { body.textContent = 'Loading review…'; return; }
  if (!lessonDueRows.length) { body.textContent = 'Nothing to learn or review right now.'; return; }
  for (const row of lessonDueRows) {
    const card = document.createElement('details'); card.className = 'lee-lesson-review-card';
    const title = document.createElement('summary'); title.textContent = row.name; card.appendChild(title);
    for (const [key, cls] of [['question', 'lee-lesson-question'], ['why', 'lee-lesson-why'], ['reason', 'lee-lesson-reason']]) {
      if (!row[key]) continue;
      const p = document.createElement('p'); p.className = cls; p.textContent = row[key]; card.appendChild(p);
    }
    const show = document.createElement('button'); show.type = 'button'; show.className = 'lee-btn'; show.textContent = 'Show my last answer';
    show.onclick = () => {
      const last = document.createElement('div'); last.className = 'lee-lesson-last-answer';
      for (const [key, label] of [['answer', 'My last answer'], ['thinking', 'Thinking'], ['actual', 'Actual']]) {
        const heading = document.createElement('h4'), p = document.createElement('p');
        heading.textContent = label; p.textContent = row[key] || ''; last.append(heading, p);
      }
      show.replaceWith(last);
    };
    card.appendChild(show); body.appendChild(card);
  }
}
async function refreshLessonDue() {
  const seq = ++lessonDueSeq;
  try {
    const rows = await api('/lesson/due'); if (seq !== lessonDueSeq) return;
    lessonDueRows = rows; lessonDueError = '';
    const item = $('#lessondue');
    if (item) { item.textContent = rows.length ? `${rows.length} due` : ''; item.hidden = !rows.length; }
  } catch (e) { if (seq !== lessonDueSeq) return; lessonDueError = String(e.message || e); }
  paintLessonReview();
}
