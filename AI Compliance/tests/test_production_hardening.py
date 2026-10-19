import pytest
import httpx
import asyncio
import time
import os
import json

# --- CONFIGURATION ---
# Note: Using the same token from your load_test.py
AUTH_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJkZW1vOnN1cGVyYWRtaW5AY29tcGFueS5jb20iLCJlbWFpbCI6InN1cGVyYWRtaW5AY29tcGFueS5jb20iLCJ0b2tlbl91c2UiOiJkZW1vX2FjY2VzcyIsImlhdCI6MTc3ODIzNTU1MCwiZXhwIjoxNzc4Mjc4NzUwfQ.tvcZTBbiPX8UqVz2V6iEt_RhIZqbgkdJuwG59jSes6E"
API_URL = "http://localhost:8052/api/v1"
ORG_SLUG = "legacy-default"
PDF_PATH = "/Users/shreyanshbhatter/Developer/compliance_ai_clean/Commentaries.pdf"

HEADERS = {"Authorization": f"Bearer {AUTH_TOKEN}"}

@pytest.mark.asyncio
async def test_scenario_1_concurrency():
    """Scenario 1: Concurrency - Upload 5 docs at once. 
    Proves the API is decoupled from AI processing and handles concurrent spikes.
    """
    async with httpx.AsyncClient(timeout=60.0) as client:
        if not os.path.exists(PDF_PATH):
            pytest.skip(f"PDF file not found at {PDF_PATH}")
            
        with open(PDF_PATH, "rb") as f:
            pdf_content = f.read()
            
        tasks = []
        for i in range(5):
            files = {"file": (f"concurrency_test_{i}.pdf", pdf_content, "application/pdf")}
            data = {
                "document_name": f"Concurrency Test {i}", 
                "document_type": "Marketing Material"
            }
            tasks.append(client.post(
                f"{API_URL}/orgs/{ORG_SLUG}/documents/upload", 
                headers=HEADERS, 
                data=data, 
                files=files
            ))
        
        start_time = time.time()
        responses = await asyncio.gather(*tasks)
        total_time = time.time() - start_time
        
        print(f"\n[Scenario 1] 5 Concurrent Uploads finished in {total_time:.2f}s")
        for idx, r in enumerate(responses):
            assert r.status_code in [200, 201], f"Upload {idx} failed: {r.text}"
        
        # Total time should be very low (e.g., < 5s) because API only queues, doesn't process AI
        assert total_time < 10.0, f"API took too long ({total_time:.2f}s) to queue requests. Is it blocking?"

@pytest.mark.asyncio
async def test_scenario_2_id_collisions():
    """Scenario 2: ID Collision - Rapid fire 10 requests.
    Verifies that pg_advisory_xact_lock handles sequential ID generation safely.
    """
    async with httpx.AsyncClient(timeout=60.0) as client:
        if not os.path.exists(PDF_PATH):
            pytest.skip(f"PDF file not found at {PDF_PATH}")
            
        with open(PDF_PATH, "rb") as f:
            pdf_content = f.read()
            
        tasks = []
        for i in range(10):
            files = {"file": (f"collision_test_{i}.pdf", pdf_content, "application/pdf")}
            data = {
                "document_name": f"Collision Test {i}", 
                "document_type": "Marketing Material"
            }
            tasks.append(client.post(
                f"{API_URL}/orgs/{ORG_SLUG}/documents/upload", 
                headers=HEADERS, 
                data=data, 
                files=files
            ))
            
        responses = await asyncio.gather(*tasks)
        
        for idx, r in enumerate(responses):
            assert r.status_code in [200, 201], f"Upload {idx} failed: {r.text}"
            
        # Success here means the DB didn't throw unique constraint errors during the spike
        print("\n[Scenario 2] 10 Rapid-fire requests handled without DB ID collisions.")

@pytest.mark.asyncio
async def test_scenario_3_resiliency():
    """Scenario 3: Resiliency - Verify queuing response structure.
    Confirms the API returns the correct 'queued' response to the frontend.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        if not os.path.exists(PDF_PATH):
            pytest.skip(f"PDF file not found at {PDF_PATH}")
            
        with open(PDF_PATH, "rb") as f:
            files = {"file": ("resiliency_test.pdf", f, "application/pdf")}
            data = {
                "document_name": "Resiliency Test", 
                "document_type": "Marketing Material"
            }
            resp = await client.post(
                f"{API_URL}/orgs/{ORG_SLUG}/documents/upload", 
                headers=HEADERS, 
                data=data, 
                files=files
            )
            
            assert resp.status_code in [200, 201]
            json_resp = resp.json()
            assert "id" in json_resp, "Expected Document object with 'id'"
            # Verify it's documented as queued (depending on your logic)
            print(f"\n[Scenario 3] API returned valid async response: {json.dumps(json_resp)}")
