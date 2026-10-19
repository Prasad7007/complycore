import asyncio
import os
import sys

from botocore.exceptions import ClientError
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# We need to import the DB and Cognito clients from the app
try:
    from apis.core.database import db_pool, init_db, close_db
    from apis.v1.routers.auth import cognito_client, resolve_cognito_username
    from apis.core.security import COGNITO_USER_POOL_ID
except ImportError:
    print("Error: Could not import application modules. Make sure you run this script from the 'AI Compliance' directory.")
    sys.exit(1)

async def recover_ghost_user(email: str):
    print(f"Starting recovery for ghost user: {email}")
    await init_db()
    
    try:
        # 1. Check and Delete from Cognito
        print("1. Checking Cognito...")
        cognito_username = resolve_cognito_username(email)
        if cognito_username:
            print(f"   Found in Cognito (Username: {cognito_username}). Deleting...")
            try:
                cognito_client.admin_delete_user(
                    UserPoolId=COGNITO_USER_POOL_ID,
                    Username=cognito_username
                )
                print("   ✅ Successfully deleted from Cognito.")
            except ClientError as e:
                print(f"   ❌ Failed to delete from Cognito: {e}")
        else:
            print("   ✅ Not found in Cognito (already clean).")

        # 2. Check and Delete from Database
        print("\n2. Checking Database...")
        async with db_pool.acquire() as db:
            profile = await db.fetchrow(
                "SELECT id, is_active FROM user_profiles WHERE lower(email) = lower($1)", 
                email
            )
            
            if profile:
                user_id = profile["id"]
                print(f"   Found in DB (User ID: {user_id}, Active: {profile['is_active']}). Cleaning up...")
                
                async with db.transaction():
                    # Delete associative rows first
                    await db.execute("DELETE FROM organization_users WHERE user_id = $1", user_id)
                    print("   ✅ Removed from organization_users.")
                    
                    await db.execute("DELETE FROM user_roles WHERE user_id = $1", user_id)
                    print("   ✅ Removed from user_roles.")
                    
                    # Try hard delete first
                    try:
                        await db.execute("DELETE FROM user_profiles WHERE id = $1", user_id)
                        print("   ✅ Profile hard-deleted from user_profiles.")
                    except Exception as e:
                        if "foreign key constraint" in str(e).lower():
                            print("   ⚠️ Cannot hard-delete due to foreign key constraints (user has uploaded documents or audit logs).")
                            await db.execute("UPDATE user_profiles SET is_active = FALSE WHERE id = $1", user_id)
                            print("   ✅ Profile soft-deleted (is_active = FALSE).")
                        else:
                            raise e
            else:
                print("   ✅ Not found in Database (already clean).")
                
        print("\n🎉 Recovery complete! You can now safely re-add this user.")
                
    finally:
        await close_db()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python recover_ghost_user.py <email_address>")
        sys.exit(1)
        
    target_email = sys.argv[1].strip()
    asyncio.run(recover_ghost_user(target_email))
