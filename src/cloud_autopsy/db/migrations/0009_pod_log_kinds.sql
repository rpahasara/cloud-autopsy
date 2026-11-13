-- CA-P2-002e (provisional; authorized for the synthetic-only development environment): contract
-- profile 4, which is profile 3 with observation kinds 0.4 (container logs read through the Kubernetes
-- API pods/log subresource). Forward-only and additive. Migrations 0001-0008, ca.contract_pin and every
-- stored row are unchanged; no constraint is altered.
--
-- The new version becomes additionally supported, so a plan may pin profile 4 (checked by the 0006
-- plan trigger against ca.contract_pin and this table).

INSERT INTO ca.contract_version_supported (contract_name, contract_version) VALUES
  ('observation-kinds', 'ca-observation-kinds/0.4-provisional');
