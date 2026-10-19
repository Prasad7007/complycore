"""
Fix unconfirmed Cognito users by admin-confirming them.
Also cleans up duplicate unconfirmed accounts that share the same email alias.

Usage:
    python fix_unconfirmed_user.py <email>
    python fix_unconfirmed_user.py prasadagalave0007@gmail.com
"""
import os
import sys
import boto3
from dotenv import load_dotenv

load_dotenv()

COGNITO_USER_POOL_ID = os.getenv("COGNITO_USER_POOL_ID")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")


def fix_user(email: str):
    client = boto3.client("cognito-idp", region_name=AWS_REGION)

    print(f"\n🔍 Looking up all Cognito accounts with email: {email}")
    response = client.list_users(
        UserPoolId=COGNITO_USER_POOL_ID,
        Filter=f'email = "{email}"',
        Limit=10,
    )
    users = response.get("Users", [])

    if not users:
        print(f"❌ No user found with email: {email}")
        return

    print(f"Found {len(users)} account(s):")
    for u in users:
        print(f"  Username: {u['Username']}  Status: {u['UserStatus']}")

    confirmed = [u for u in users if u["UserStatus"] == "CONFIRMED"]
    unconfirmed = [u for u in users if u["UserStatus"] != "CONFIRMED"]

    if confirmed:
        print(f"\n✅ User already has a CONFIRMED account: {confirmed[0]['Username']}")
    
    # Admin-confirm any unconfirmed accounts
    for u in unconfirmed:
        uname = u["Username"]
        print(f"\n⚙️  Admin-confirming unconfirmed user: {uname}")
        try:
            client.admin_confirm_sign_up(
                UserPoolId=COGNITO_USER_POOL_ID,
                Username=uname,
            )
            print(f"  ✅ Confirmed: {uname}")
        except client.exceptions.InvalidParameterException as e:
            print(f"  ℹ️  Already confirmed or in invalid state: {e}")
        except Exception as e:
            print(f"  ❌ Failed to confirm {uname}: {e}")

    # If there are MULTIPLE confirmed accounts (error state), delete the extras
    if len(confirmed) > 1:
        print(f"\n⚠️  Multiple CONFIRMED accounts for same email! Deleting duplicates...")
        keep = confirmed[0]
        for u in confirmed[1:]:
            try:
                client.admin_delete_user(
                    UserPoolId=COGNITO_USER_POOL_ID,
                    Username=u["Username"],
                )
                print(f"  🗑️  Deleted duplicate: {u['Username']}")
            except Exception as e:
                print(f"  ❌ Failed to delete duplicate {u['Username']}: {e}")
        print(f"  ✅ Kept: {keep['Username']}")

    print("\n🎉 Done! The user should now be able to log in.")


if __name__ == "__main__":
    email_arg = sys.argv[1] if len(sys.argv) > 1 else None
    if not email_arg:
        print("Usage: python fix_unconfirmed_user.py <email>")
        sys.exit(1)
    fix_user(email_arg)
