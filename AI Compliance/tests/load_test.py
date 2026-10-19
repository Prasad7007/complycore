import requests
import threading
import time
import concurrent.futures
import sys

# --- CONFIGURATION ---
# Replace this with a valid auth token from your browser (Local Storage -> auth_token)
AUTH_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJkZW1vOnN1cGVyYWRtaW5AY29tcGFueS5jb20iLCJlbWFpbCI6InN1cGVyYWRtaW5AY29tcGFueS5jb20iLCJ0b2tlbl91c2UiOiJkZW1vX2FjY2VzcyIsImlhdCI6MTc3ODA1NDk5MSwiZXhwIjoxNzc4MDk4MTkxfQ.9uyyrCosFvaERkPe9arv6MqJY4-r4DMCSRBknoTvu0c"
API_URL = "http://localhost:8052/api/v1"
PDF_PATH = "/Users/shreyanshbhatter/Developer/compliance_ai_clean/Commentaries.pdf"  # Make sure this file exists in the same folder, or provide absolute path

# Headers for all requests
HEADERS = {
    "Authorization": f"Bearer {AUTH_TOKEN}",
    "X-Tenant-ID": "1"  # Or whatever your standard tenant ID is
}
ORG_SLUG = "legacy-default"  # Try 'elevatetrust' or 'default'. Check your URL in the browser when viewing a document.

# -------------------------------------------------------------------------------------

def ping_server_continuously(stop_event):
    """
    Simulates User #11 trying to use the app while it is under heavy load.
    Pings the user profile endpoint every 1 second and prints the response time.
    """
    print(f"\\n[Monitor] Starting API responsiveness monitor...")
    while not stop_event.is_set():
        start_time = time.time()
        try:
            # A simple, lightweight endpoint that requires a database connection
            resp = requests.get(f"{API_URL}/users/me", headers=HEADERS, timeout=10)
            elapsed = time.time() - start_time
            
            if resp.status_code == 200:
                print(f"[Monitor] API Ping: {elapsed:.3f}s (OK)")
            else:
                print(f"[Monitor] API Ping: {elapsed:.3f}s (FAIL - HTTP {resp.status_code})")
        
        except requests.exceptions.RequestException as e:
            print(f"[Monitor] API Ping: FAILED (Connection Error/Timeout) - {e}")
            
        time.sleep(1)

def upload_document(thread_id):
    """
    Simulates a single user uploading a complex PDF.
    """
    start_time = time.time()
    try:
        with open(PDF_PATH, "rb") as f:
            files = {"file": ("test_doc.pdf", f, "application/pdf")}
            data = {
                "document_name": f"Load Test Doc {thread_id}",
                "document_type": "Marketing Material"
            }
            resp = requests.post(
                f"{API_URL}/orgs/{ORG_SLUG}/documents/upload", 
                headers=HEADERS, 
                data=data, 
                files=files
            )
            elapsed = time.time() - start_time
            if resp.status_code == 200:
                print(f"[Upload #{thread_id}] Started successfully in {elapsed:.2f}s")
                return True
            else:
                print(f"[Upload #{thread_id}] Failed with HTTP {resp.status_code} in {elapsed:.2f}s")
                print(f"Error: {resp.text}")
                return False
    except FileNotFoundError:
        print(f"[Error] Could not find the file '{PDF_PATH}'. Please update the PDF_PATH variable.")
        sys.exit(1)
    except Exception as e:
        print(f"[Upload #{thread_id}] Exception: {e}")
        return False

def run_load_test():
    if AUTH_TOKEN == "YOUR_AUTH_TOKEN_HERE":
        print("ERROR: Please paste your auth token into the AUTH_TOKEN variable at the top of this script.")
        return

    print("=" * 60)
    print("STARTING BASELINE LOAD TEST (10 CONCURRENT USERS)")
    print("=" * 60)
    print("Instructions:")
    print("1. Open another terminal and run 'docker stats'")
    print("2. Watch the Memory and CPU usage for your backend container.")
    print("=" * 60)
    time.sleep(3)

    # 1. Start the background ping monitor
    stop_event = threading.Event()
    monitor_thread = threading.Thread(target=ping_server_continuously, args=(stop_event,))
    monitor_thread.daemon = True
    monitor_thread.start()

    # Let the monitor print a few baselines first
    time.sleep(3)

    # 2. Fire 10 concurrent uploads
    concurrent_users = 10
    print(f"\\n[Load] Firing {concurrent_users} simultaneous PDF uploads...")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrent_users) as executor:
        # Submit all 10 tasks at once
        futures = [executor.submit(upload_document, i) for i in range(1, concurrent_users + 1)]
        
        # Wait for all uploads to complete
        concurrent.futures.wait(futures)

    print("\\n[Load] All 10 upload requests have returned.")
    print("[Load] The server is now crunching the AI tasks in the background.")
    print("[Load] Keep watching the Monitor pings and 'docker stats'.")
    print("[Load] Press Ctrl+C to stop the monitor when you are satisfied with the test.\\n")
    
    try:
        # Keep the main thread alive so the daemon monitor thread can keep printing
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\\n[Monitor] Stopping test.")
        stop_event.set()
        monitor_thread.join()

if __name__ == "__main__":
    run_load_test()
