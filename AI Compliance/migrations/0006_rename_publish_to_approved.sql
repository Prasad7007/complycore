-- Migration to rename 'publish' stage to 'approved'
-- This ensures that documents previously in the 'publish' stage are now correctly identified as 'approved'.

UPDATE workflows 
SET current_stage = 'approved' 
WHERE current_stage = 'publish';

UPDATE workflow_steps
SET stage = 'approved'
WHERE stage = 'publish';

UPDATE workflow_steps
SET previous_stage = 'approved'
WHERE previous_stage = 'publish';
