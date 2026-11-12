-- CA-P2-004f (provisional; authorized for the synthetic-only development environment): contract
-- profile 3 for collector list + watch runs, pinning acquisition batch 0.2 and observation kinds 0.3.
-- Forward-only and additive. Migrations 0001-0007, ca.contract_pin and every stored row are unchanged.
--
-- 1. The two versions become additionally supported, so a plan may pin profile 3 (checked by the
--    0006 plan trigger against ca.contract_pin and this table).
-- 2. The version CHECK on ca.acquisition_batch is widened from exactly 0.1 to 0.1 or 0.2. Every stored
--    row is a 0.1 batch, which satisfies both the old and the new constraint; adding the new
--    constraint re-validates every existing row. Any other version is still refused.

INSERT INTO ca.contract_version_supported (contract_name, contract_version) VALUES
  ('acquisition-batch', 'ca-acquisition-batch/0.2-provisional'),
  ('observation-kinds', 'ca-observation-kinds/0.3-provisional');

ALTER TABLE ca.acquisition_batch DROP CONSTRAINT acquisition_batch_contract_version_check;
ALTER TABLE ca.acquisition_batch ADD CONSTRAINT acquisition_batch_contract_version_check
  CHECK (contract_version IN ('ca-acquisition-batch/0.1-provisional', 'ca-acquisition-batch/0.2-provisional'));
