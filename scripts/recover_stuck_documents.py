import asyncio
import apis.core.database as db_module
import asyncpg
from apis.services.celery_tasks import classify_document_task

async def run():
    print("Connecting to database...")
    pool = await asyncpg.create_pool(db_module.DATABASE_URL)
    
    stuck_docs = []
    
    async with pool.acquire() as db:
        # Find all documents where the current review has not completed classification or analysis
        rows = await db.fetch("""
            SELECT 
                d.id as doc_id, 
                d.name, 
                dv.id as version_id, 
                dv.s3_bucket, 
                dv.s3_key, 
                d.organization_id,
                cr.workflow_stage as initial_stage,
                d.submitted_by as user_id
            FROM documents d
            JOIN document_versions dv ON d.current_version_id = dv.id
            JOIN content_reviews cr ON cr.document_version_id = dv.id
            WHERE NOT EXISTS (
                SELECT 1 FROM audit_events ae 
                WHERE ae.review_id = cr.id AND ae.event_type IN ('ai_classification_completed', 'ai_analysis_completed')
            )
        """)
        
        for row in rows:
            stuck_docs.append(dict(row))

    if not stuck_docs:
        print("No stuck documents found!")
        return ̰

    print(f"Found {len(stuck_docs)} stuck documents. Re-queueing tasks...")
    
    # for doc in stuck_docs:
    #     print(f"Queueing recovery for: {doc['name']} (doc_id: {doc['doc_id']})")
    #     # Trigger the Celery background task exactly like the upload endpoint does
    #     classify_document_task.delay(
    #         doc_id=str(doc['doc_id']),
    #         version_id=str(doc['version_id']),
    #         bucket=doc['s3_bucket'] or "demo-bucket",
    #         s3_key=doc['s3_key'],
    #         user_id=str(doc['user_id']),
    #         initial_stage=doc['initial_stage'],
    #         organization_id=str(doc['organization_id']) if doc['organization_id'] else None
    #     )
        
    # print("Recovery complete. Check the worker logs to monitor progress.")

if __name__ == "__main__":
    asyncio.run(run())
