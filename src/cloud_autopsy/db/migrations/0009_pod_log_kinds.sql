-- CA-P2-002e (provisional; authorized for the synthetic-only development environment): contract
-- profile 4, which pins observation kinds 0.4 (container logs read through the Kubernetes API pods/log
-- subresource) and acquisition batch 0.3 (M11: the log_sequence_continuity coverage basis).
-- Forward-only and additive. Migrations 0001-0008, ca.contract_pin and every stored row are unchanged.
--
-- 1. The two versions become additionally supported, so a plan may pin profile 4 (checked by the 0006
--    plan trigger against ca.contract_pin and this table).
-- 2. The version CHECK on ca.acquisition_batch is widened from 0.1 or 0.2 to 0.1, 0.2 or 0.3. Every
--    stored row is a 0.1 or 0.2 batch, which satisfies both the old and the new constraint; adding the new
--    constraint re-validates every existing row. Any other version is still refused.

INSERT INTO ca.contract_version_supported (contract_name, contract_version) VALUES
  ('acquisition-batch', 'ca-acquisition-batch/0.3-provisional'),
  ('observation-kinds', 'ca-observation-kinds/0.4-provisional');

ALTER TABLE ca.acquisition_batch DROP CONSTRAINT acquisition_batch_contract_version_check;
ALTER TABLE ca.acquisition_batch ADD CONSTRAINT acquisition_batch_contract_version_check
  CHECK (contract_version IN ('ca-acquisition-batch/0.1-provisional', 'ca-acquisition-batch/0.2-provisional',
                              'ca-acquisition-batch/0.3-provisional'));
