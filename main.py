"""In-class practice quiz.

The instructor opens the site, which creates a session and two links: a host
page (instructor only) and a student link to share. The instructor samples
random problems from the practice-problems PDF; students answer; the instructor
reveals the response statistics and/or the official solution.

All state is in memory. Run with a single worker process (see Procfile).
"""
import os
import random
import secrets
import threading
from collections import Counter

from flask import Flask, abort, jsonify, redirect, render_template, request, url_for

import problems

app = Flask(__name__)

PROBLEMS = problems.load()
BY_ID = {p["id"]: p for p in PROBLEMS}
CHAPTERS = sorted({(p["chapter"], p["chapter_title"]) for p in PROBLEMS})
DIFFICULTIES = ["Easy", "Medium", "Hard", "Extra hard"]
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

SESSIONS = {}  # code -> session dict
LOCK = threading.Lock()


def _new_session():
    code = "".join(random.choices(CODE_ALPHABET, k=5))
    while code in SESSIONS:
        code = "".join(random.choices(CODE_ALPHABET, k=5))
    session = {
        "code": code,
        "host_key": secrets.token_urlsafe(16),
        "chapters": [c for c, _ in CHAPTERS],
        "difficulties": list(DIFFICULTIES),
        "types": ["MC", "SA"],
        "asked": [],          # problem ids already shown, in order
        "current": None,      # problem id currently on screen
        "show_responses": False,
        "show_solution": False,
        "responses": {},      # problem id -> {student_id: answer}
        "version": 0,         # bumped on every change so clients know when to re-render
    }
    SESSIONS[code] = session
    return session


def _get_session(code):
    session = SESSIONS.get(code.upper())
    if session is None:
        abort(404)
    return session


def _host_key_from_request():
    if request.args.get("key"):
        return request.args["key"]
    if request.headers.get("X-Host-Key"):
        return request.headers["X-Host-Key"]
    if request.is_json and isinstance(request.json, dict):
        return request.json.get("key")
    return None


def _require_host(session):
    if _host_key_from_request() != session["host_key"]:
        abort(403)


def _pool(session):
    return [
        p for p in PROBLEMS
        if p["chapter"] in session["chapters"]
        and p["difficulty"] in session["difficulties"]
        and p["type"] in session["types"]
    ]


def _public_problem(p):
    """The problem as students may see it: without the answer."""
    return {k: v for k, v in p.items() if k not in ("answer", "correct")}


def _stats(session, pid):
    p = BY_ID[pid]
    answers = session["responses"].get(pid, {})
    if p["type"] == "MC":
        counts = Counter(answers.values())
        return {
            "total": len(answers),
            "counts": {o["letter"]: counts.get(o["letter"], 0) for o in p["options"]},
        }
    return {"total": len(answers), "answers": sorted(answers.values(), key=str.lower)}


def _state(session, host=False):
    pid = session["current"]
    state = {
        "code": session["code"],
        "version": session["version"],
        "show_responses": session["show_responses"],
        "show_solution": session["show_solution"],
        "asked": len(session["asked"]),
        "pool": len(_pool(session)),
        "problem": None,
        "responded": 0,
        "stats": None,
        "solution": None,
    }
    if pid:
        p = BY_ID[pid]
        state["problem"] = _public_problem(p)
        state["responded"] = len(session["responses"].get(pid, {}))
        if host or session["show_responses"]:
            state["stats"] = _stats(session, pid)
        if host or session["show_solution"]:
            state["solution"] = {"answer": p["answer"], "correct": p.get("correct")}
    if host:
        state["chapters"] = session["chapters"]
        state["difficulties"] = session["difficulties"]
        state["types"] = session["types"]
    return state


# ----------------------------------------------------------------- pages

@app.route("/")
def index():
    return render_template("index.html", n=len(PROBLEMS), chapters=CHAPTERS)


@app.route("/start", methods=["POST"])
def start():
    with LOCK:
        session = _new_session()
    return redirect(url_for("host", code=session["code"], key=session["host_key"]))


@app.route("/host/<code>")
def host(code):
    session = _get_session(code)
    _require_host(session)
    student_url = url_for("student", code=session["code"], _external=True)
    return render_template(
        "host.html",
        code=session["code"],
        key=session["host_key"],
        student_url=student_url,
        chapters=CHAPTERS,
        difficulties=DIFFICULTIES,
    )


@app.route("/s/<code>")
def student(code):
    session = _get_session(code)
    return render_template("student.html", code=session["code"])


@app.route("/join", methods=["POST"])
def join():
    code = (request.form.get("code") or "").strip().upper()
    if code not in SESSIONS:
        return render_template("index.html", n=len(PROBLEMS), chapters=CHAPTERS,
                               error=f"No session with code {code or '(blank)'}."), 404
    return redirect(url_for("student", code=code))


# ----------------------------------------------------------------- API

@app.route("/api/<code>/state")
def api_state(code):
    session = _get_session(code)
    host = request.args.get("key") == session["host_key"]
    with LOCK:
        return jsonify(_state(session, host=host))


@app.route("/api/<code>/next", methods=["POST"])
def api_next(code):
    session = _get_session(code)
    _require_host(session)
    with LOCK:
        pool = _pool(session)
        if not pool:
            return jsonify({"error": "No problems match the current filters."}), 400
        remaining = [p for p in pool if p["id"] not in session["asked"]]
        if not remaining:  # every problem in the pool has been asked: start over
            session["asked"] = []
            remaining = pool
        chosen = random.choice(remaining)
        session["asked"].append(chosen["id"])
        session["current"] = chosen["id"]
        session["show_responses"] = False
        session["show_solution"] = False
        session["version"] += 1
        return jsonify(_state(session, host=True))


@app.route("/api/<code>/toggle", methods=["POST"])
def api_toggle(code):
    session = _get_session(code)
    _require_host(session)
    what = (request.json or {}).get("what")
    if what not in ("show_responses", "show_solution"):
        abort(400)
    with LOCK:
        session[what] = not session[what]
        session["version"] += 1
        return jsonify(_state(session, host=True))


@app.route("/api/<code>/filters", methods=["POST"])
def api_filters(code):
    session = _get_session(code)
    _require_host(session)
    data = request.json or {}
    with LOCK:
        if "chapters" in data:
            session["chapters"] = [int(c) for c in data["chapters"]]
        if "difficulties" in data:
            session["difficulties"] = [d for d in data["difficulties"] if d in DIFFICULTIES]
        if "types" in data:
            session["types"] = [t for t in data["types"] if t in ("MC", "SA")]
        session["version"] += 1
        return jsonify(_state(session, host=True))


@app.route("/api/<code>/answer", methods=["POST"])
def api_answer(code):
    session = _get_session(code)
    data = request.json or {}
    student_id = str(data.get("student_id", ""))[:64]
    answer = str(data.get("answer", "")).strip()[:1000]
    pid = data.get("problem_id")
    if not student_id or not answer:
        abort(400)
    with LOCK:
        if pid != session["current"]:
            return jsonify({"error": "That question is no longer open."}), 409
        p = BY_ID[pid]
        if p["type"] == "MC" and answer not in {o["letter"] for o in p["options"]}:
            abort(400)
        session["responses"].setdefault(pid, {})[student_id] = answer
        session["version"] += 1
        return jsonify({"ok": True, "responded": len(session["responses"][pid])})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), debug=True)
