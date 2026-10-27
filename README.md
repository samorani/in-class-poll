# in-class-poll

A small Flask app for running practice-quiz sessions in class. The problems and
their answers come from `files/practice-problems.pdf`.

## How it works

1. The instructor opens the site and clicks **Start a session**. This creates a
   session with a 5-letter code and opens the host page (its URL contains a
   private key; do not project it).
2. The host page shows the student link (and a QR code) to share. Students open
   it, or enter the code on the home page.
3. **Next question** draws a random problem that has not been shown yet in this
   session (filters let you restrict chapters, difficulty, and MC/SA).
4. Students answer: pick an option (multiple choice) or type a sentence (short
   answer). They can change their answer until the next question.
5. **Show responses** reveals the tally (bar chart for MC, list for SA) on the
   host page and on students' screens. **Show solution** reveals the answer from
   the PDF and highlights the correct option.

State lives in memory, so the app must run as a single process (the Procfile
uses one gunicorn worker with threads) and, on Cloud Run, a single instance.

## Run locally

```
pip install -r requirements.txt
python main.py
```

Then open http://127.0.0.1:8080.

`files/problems.json` is a cache of the parsed PDF. It is rebuilt automatically
when the PDF is newer, or by hand with `python problems.py`.

## Deploy to Google Cloud Run

```
bash gcp_setup.sh --project YOUR-PROJECT-ID --billing YOUR-BILLING-ID
```

After the first deploy, pin the service to one instance so every student talks
to the same process:

```
gcloud run services update YOUR-PROJECT-ID --region us-west1 --max-instances 1 --min-instances 1
```

(`--min-instances 1` is optional; it keeps the session alive between questions
instead of letting Cloud Run shut the idle container down. Set it back to 0
after class.) A redeploy also restarts the process and forgets any open session.
