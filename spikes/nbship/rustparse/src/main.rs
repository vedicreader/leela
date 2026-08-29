//! Read Rust on stdin, write JSON on stdout saying what a PyO3 binding could be written for.
//!
//! The Python side used to do this with regular expressions, which cannot see a generic parameter,
//! a lifetime, a `where` clause or a nested module, and so quietly generated bindings that did not
//! compile. This is `syn`, the parser rustc's own macro ecosystem uses, so what comes out is the
//! real shape of the code -- including, for every item that cannot cross into Python, the reason.

use std::collections::HashSet;
use std::io::{self, Read, Write};

use quote::ToTokens;
use serde_json::{json, Value};
use syn::{
    Attribute, Expr, Fields, FnArg, ImplItem, Item, Lit, Meta, Pat, ReturnType, Signature, Type,
    Visibility,
};

/// Types PyO3 converts on its own. Anything else has to be a type this crate also exports.
const SCALARS: &[&str] = &[
    "i8", "i16", "i32", "i64", "i128", "isize", "u8", "u16", "u32", "u64", "u128", "usize", "f32",
    "f64", "bool", "char", "String", "&str", "()",
];

/// Token streams print with spaces around every punctuation mark. Put it back how a person writes it.
fn norm(s: String) -> String {
    let mut out = s;
    for (from, to) in [
        (" :: ", "::"), (" ::", "::"), (":: ", "::"),
        (" < ", "<"), (" <", "<"), ("< ", "<"),
        (" > ", ">"), (" >", ">"), ("> ", ">"),
        (" ,", ","), ("& ", "&"), (" ;", ";"),
        (" (", "("), ("( ", "("), (" )", ")"),
        (" [", "["), ("[ ", "["), (" ]", "]"),
    ] {
        out = out.replace(from, to);
    }
    out.trim().to_string()
}

fn ty_str(t: &Type) -> String { norm(t.to_token_stream().to_string()) }

fn ret_str(r: &ReturnType) -> String {
    match r {
        ReturnType::Default => "()".to_string(),
        ReturnType::Type(_, t) => ty_str(t),
    }
}

fn is_pub(v: &Visibility) -> bool { matches!(v, Visibility::Public(_)) }

/// The `///` lines above an item, joined. These become the Python docstring.
fn docs(attrs: &[Attribute]) -> String {
    let lines: Vec<String> = attrs
        .iter()
        .filter_map(|a| {
            if !a.path().is_ident("doc") { return None; }
            let Meta::NameValue(nv) = &a.meta else { return None };
            let Expr::Lit(e) = &nv.value else { return None };
            let Lit::Str(s) = &e.lit else { return None };
            Some(s.value().trim().to_string())
        })
        .collect();
    lines.join("\n")
}

fn derives(attrs: &[Attribute]) -> Vec<String> {
    let mut out = Vec::new();
    for a in attrs {
        if !a.path().is_ident("derive") { continue; }
        let _ = a.parse_nested_meta(|m| {
            if let Some(i) = m.path.get_ident() { out.push(i.to_string()); }
            Ok(())
        });
    }
    out
}

/// Split `A, B` on commas that are not inside brackets.
fn split_top(s: &str) -> Vec<String> {
    let (mut out, mut depth, mut cur) = (Vec::new(), 0i32, String::new());
    for c in s.chars() {
        match c {
            '<' | '(' | '[' => depth += 1,
            '>' | ')' | ']' => depth -= 1,
            ',' if depth <= 0 => { out.push(cur.trim().to_string()); cur.clear(); continue; }
            _ => {}
        }
        cur.push(c);
    }
    if !cur.trim().is_empty() { out.push(cur.trim().to_string()); }
    out
}

fn inner_of<'a>(t: &'a str, wrap: &str) -> Option<&'a str> {
    t.strip_prefix(&format!("{wrap}<"))?.strip_suffix('>')
}

/// Why this type cannot cross into Python, or None when it can.
fn why_not(ty: &str, locals: &HashSet<String>) -> Option<String> {
    let t = ty.trim();
    if t.is_empty() || t == "Self" || SCALARS.contains(&t) || locals.contains(t) { return None; }
    for wrap in ["Vec", "Option"] {
        if let Some(inner) = inner_of(t, wrap) { return why_not(inner, locals); }
    }
    if let Some(inner) = inner_of(t, "Result") {
        // `Result` is the good case: PyO3 turns the error into a Python exception.
        return why_not(split_top(inner).first().map(|s| s.as_str()).unwrap_or(""), locals);
    }
    if let Some(inner) = inner_of(t, "HashMap").or_else(|| inner_of(t, "BTreeMap")) {
        return split_top(inner).iter().find_map(|p| why_not(p, locals));
    }
    if t.starts_with('&') {
        return Some(format!("`{t}` is a borrow; PyO3 needs an owned value here (try `String`)"));
    }
    if t.starts_with("impl ") || t.starts_with("dyn ") {
        return Some(format!("`{t}` has no single concrete type for Python to hold"));
    }
    if t.contains('<') {
        return Some(format!("`{t}` is generic over something this exporter cannot map"));
    }
    Some(format!("`{t}` is not a type this exporter knows how to bind"))
}

/// Why this signature cannot cross, checking the shape before the types.
fn sig_skip(sig: &Signature, locals: &HashSet<String>) -> Option<String> {
    if !sig.generics.params.is_empty() {
        let g = norm(sig.generics.params.to_token_stream().to_string());
        return Some(format!("takes a generic parameter `{g}`, which PyO3 cannot bind"));
    }
    if sig.generics.where_clause.is_some() {
        return Some("has a `where` clause, which PyO3 cannot bind".to_string());
    }
    if sig.unsafety.is_some() { return Some("is `unsafe`".to_string()); }
    for a in &sig.inputs {
        if let FnArg::Typed(p) = a {
            let t = ty_str(&p.ty);
            if let Some(w) = why_not(&t, locals) { return Some(format!("argument {w}")); }
        }
    }
    let r = ret_str(&sig.output);
    why_not(&r, locals).map(|w| format!("return type {w}"))
}

/// `(name, type)` for each argument that is not the receiver.
fn args(sig: &Signature) -> Vec<Value> {
    sig.inputs
        .iter()
        .filter_map(|a| match a {
            FnArg::Receiver(_) => None,
            FnArg::Typed(p) => {
                let name = match &*p.pat {
                    Pat::Ident(i) => i.ident.to_string(),
                    other => norm(other.to_token_stream().to_string()),
                };
                Some(json!({"name": name, "ty": ty_str(&p.ty)}))
            }
        })
        .collect()
}

fn receiver(sig: &Signature) -> Option<String> {
    sig.inputs.iter().find_map(|a| match a {
        FnArg::Receiver(r) => Some(norm(r.to_token_stream().to_string())),
        _ => None,
    })
}

fn fn_json(sig: &Signature, attrs: &[Attribute], locals: &HashSet<String>) -> Value {
    json!({
        "name": sig.ident.to_string(),
        "doc": docs(attrs),
        "recv": receiver(sig),
        "args": args(sig),
        "ret": ret_str(&sig.output),
        "is_async": sig.asyncness.is_some(),
        "skip": sig_skip(sig, locals),
    })
}

/// Every item, at any module depth. A `mod` in a notebook cell is still exported code.
fn walk<'a>(items: &'a [Item], out: &mut Vec<&'a Item>) {
    for it in items {
        out.push(it);
        if let Item::Mod(m) = it {
            if let Some((_, inner)) = &m.content { walk(inner, out); }
        }
    }
}

fn main() -> io::Result<()> {
    let mut src = String::new();
    io::stdin().read_to_string(&mut src)?;
    let file: syn::File = match syn::parse_file(&src) {
        Ok(f) => f,
        Err(e) => {
            let msg = json!({"error": e.to_string(), "line": e.span().start().line});
            println!("{msg}");
            io::stdout().flush()?;
            std::process::exit(2);
        }
    };

    let mut flat: Vec<&Item> = Vec::new();
    walk(&file.items, &mut flat);

    // First pass: which types this crate defines, so a signature naming one of them is bindable.
    let mut locals: HashSet<String> = HashSet::new();
    for it in &flat {
        match it {
            Item::Struct(s) if is_pub(&s.vis) => { locals.insert(s.ident.to_string()); }
            Item::Enum(e) if is_pub(&e.vis) => { locals.insert(e.ident.to_string()); }
            _ => {}
        }
    }

    // Inherent methods, gathered per type before the structs are emitted.
    let mut methods: std::collections::HashMap<String, Vec<Value>> = Default::default();
    let mut statics: std::collections::HashMap<String, Vec<Value>> = Default::default();
    for it in &flat {
        let Item::Impl(im) = it else { continue };
        if im.trait_.is_some() { continue; }              // a trait impl is not the type's own API
        let name = ty_str(&im.self_ty);
        if !locals.contains(&name) { continue; }
        for m in &im.items {
            let ImplItem::Fn(f) = m else { continue };
            if !is_pub(&f.vis) { continue; }
            let row = fn_json(&f.sig, &f.attrs, &locals);
            if receiver(&f.sig).is_some() { methods.entry(name.clone()).or_default().push(row); }
            else { statics.entry(name.clone()).or_default().push(row); }
        }
    }

    let mut out: Vec<Value> = Vec::new();
    for it in &flat {
        match it {
            Item::Fn(f) if is_pub(&f.vis) => {
                let mut row = fn_json(&f.sig, &f.attrs, &locals);
                row["kind"] = json!("fn");
                out.push(row);
            }
            Item::Struct(s) if is_pub(&s.vis) => {
                let name = s.ident.to_string();
                let generic = !s.generics.params.is_empty();
                let fields: Vec<Value> = match &s.fields {
                    Fields::Named(n) => n
                        .named
                        .iter()
                        .filter(|f| is_pub(&f.vis))
                        .map(|f| {
                            let t = ty_str(&f.ty);
                            json!({"name": f.ident.as_ref().unwrap().to_string(), "ty": t,
                                   "skip": why_not(&t, &locals)})
                        })
                        .collect(),
                    _ => Vec::new(),
                };
                out.push(json!({
                    "kind": "struct", "name": name, "doc": docs(&s.attrs),
                    "derives": derives(&s.attrs), "fields": fields,
                    "methods": methods.remove(&name).unwrap_or_default(),
                    "statics": statics.remove(&name).unwrap_or_default(),
                    "tuple": matches!(s.fields, Fields::Unnamed(_)),
                    "skip": if generic { Some("is generic, and PyO3 binds one concrete type at a time") } else { None },
                }));
            }
            Item::Enum(e) if is_pub(&e.vis) => {
                out.push(json!({
                    "kind": "enum", "name": e.ident.to_string(), "doc": docs(&e.attrs),
                    "derives": derives(&e.attrs),
                    "variants": e.variants.iter().map(|v| v.ident.to_string()).collect::<Vec<_>>(),
                    "unit_only": e.variants.iter().all(|v| matches!(v.fields, Fields::Unit)),
                    "skip": Value::Null,
                }));
            }
            Item::Trait(t) if is_pub(&t.vis) => {
                out.push(json!({"kind": "trait", "name": t.ident.to_string(),
                                "skip": "traits have no Python equivalent to bind to"}));
            }
            _ => {}
        }
    }
    println!("{}", json!({"items": out}));
    io::stdout().flush()
}
