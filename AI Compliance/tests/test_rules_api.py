import requests
import json

base_url = "http://127.0.0.1:8052/api/v1/rules"

def test_api():
    print("Testing Compliance Rules API...")
    
    # 1. Create a rule
    print("\n1. Creating a rule...")
    payload = {
        "rule_code": "TEST-001",
        "name": "Test Rule",
        "description": "A test rule description",
        "category": "Testing"
    }
    try:
        response = requests.post(base_url, json=payload)
        print(f"Status: {response.status_code}")
        print(f"Response: {response.json()}")
        
        if response.status_code == 201:
            rule_id = response.json().get("id")
            
            # 2. Get the rule
            print(f"\n2. Getting rule {rule_id}...")
            response = requests.get(f"{base_url}/{rule_id}")
            print(f"Status: {response.status_code}")
            print(f"Response: {response.json()}")
            
            # 3. Update the rule
            print(f"\n3. Updating rule {rule_id}...")
            update_payload = {"name": "Updated Test Rule"}
            response = requests.put(f"{base_url}/{rule_id}", json=update_payload)
            print(f"Status: {response.status_code}")
            print(f"Response: {response.json()}")
            
            # 4. List rules
            print("\n4. Listing all rules...")
            response = requests.get(base_url)
            print(f"Status: {response.status_code}")
            print(f"Count: {len(response.json())}")
            
            # 5. Delete the rule
            print(f"\n5. Deleting rule {rule_id}...")
            response = requests.delete(f"{base_url}/{rule_id}")
            print(f"Status: {response.status_code}")
            print(f"Response: {response.json()}")
            
    except requests.exceptions.ConnectionError:
        print("Failed to connect to the server. Is it running on localhost:8052?")

if __name__ == "__main__":
    test_api()
