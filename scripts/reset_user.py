import os
import asyncio
import boto3
import asyncpg
from dotenv import load_dotenv

load_dotenv()

COGNITO_USER_POOL_ID = os.getenv("COGNITO_USER_POOL_ID")
AWS_REGION = os.getenv("AWS_REGION")
DATABASE_URL = os.getenv("DATABASE_URL")
AWS_S3_BUCKET = os.getenv("AWS_S3_BUCKET", "education-document-store")

async def reset_all_users():
    # 1. Delete all users from Cognito
    print(f"--- Resetting Cognito User Pool: {COGNITO_USER_POOL_ID} ---")
    client = boto3.client('cognito-idp', region_name=AWS_REGION)
    
    try:
        paginator = client.get_paginator('list_users')
        pages = paginator.paginate(UserPoolId=COGNITO_USER_POOL_ID)
        
        count = 0
        for page in pages:
            for user in page.get('Users', []):
                username = user['Username']
                print(f"Deleting Cognito user: {username}...")
                try:
                    client.admin_delete_user(
                        UserPoolId=COGNITO_USER_POOL_ID,
                        Username=username
                    )
                    count += 1
                except Exception as e:
                    print(f"  ❌ Failed to delete {username}: {e}")
        
        print(f"✅ Deleted {count} users from Cognito.")
    except Exception as e:
        print(f"❌ Error listing/deleting from Cognito: {e}")

    # 2. Clear local Database
    print(f"\n--- Clearing Local Database Users ---")
    if not DATABASE_URL:
        print("⚠️ DATABASE_URL not found in .env, skipping DB reset.")
    else:
        try:
            # asyncpg does not support +asyncpg in the DSN scheme; strip it if present.
            db_url = DATABASE_URL
            if "+asyncpg" in db_url:
                db_url = db_url.replace("+asyncpg", "")
                
            conn = await asyncpg.connect(db_url)
            
            print("Truncating user_roles and user_profiles tables...")
            # TRUNCATE with CASCADE clears dependent rows in user_roles, user_profiles, etc.
            await conn.execute("TRUNCATE user_profiles CASCADE")
            
            print("✅ Local database user tables cleared.")
            await conn.close()
        except Exception as e:
            print(f"❌ Error clearing database: {e}")

    # 3. Clear S3 Bucket
    print(f"\n--- Clearing S3 Bucket: {AWS_S3_BUCKET} ---")
    try:
        s3 = boto3.resource('s3', region_name=AWS_REGION)
        bucket = s3.Bucket(AWS_S3_BUCKET)
        
        # Deletes all objects in the bucket
        bucket.objects.all().delete()
        print(f"✅ S3 bucket contents cleared.")
    except Exception as e:
        if "NoSuchBucket" in str(e):
            print(f"⚠️ Bucket {AWS_S3_BUCKET} does not exist. Skipping.")
        else:
            print(f"❌ Error clearing S3 bucket: {e}")

if __name__ == "__main__":
    confirm = input("This will DELETE ALL USERS (Cognito + DB) and ALL S3 FILES. Are you sure? (y/n): ")
    if confirm.lower() == 'y':
        asyncio.run(reset_all_users())
    else:
        print("Reset cancelled.")
