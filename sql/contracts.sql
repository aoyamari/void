-- VOID chapter 2: one row per NEAR contract that ever "launched".
-- Source: Google's public NEAR dataset (bigquery-public-data.crypto_near_mainnet_us).
--
-- A contract is any account that received a DEPLOY_CONTRACT action.
-- A contract is *active* in a month when at least @min_callers distinct
-- accounts called it that month. This filters one-wallet test deploys and
-- most single-bot pings.
-- A contract *launched* if its busiest month reached @launch_min_callers callers.
WITH deploys AS (
  SELECT receipt_receiver_account_id AS contract,
         MIN(block_date) AS first_deploy
  FROM `bigquery-public-data.crypto_near_mainnet_us.receipt_actions`
  WHERE action_kind = 'DEPLOY_CONTRACT'
    AND block_date >= @start_date
  GROUP BY contract
),
monthly AS (
  SELECT receipt_receiver_account_id AS contract,
         DATE_TRUNC(block_date, MONTH) AS month,
         COUNT(*) AS calls,
         COUNT(DISTINCT receipt_predecessor_account_id) AS callers
  FROM `bigquery-public-data.crypto_near_mainnet_us.receipt_actions`
  WHERE action_kind = 'FUNCTION_CALL'
    AND block_date >= @start_date
  GROUP BY contract, month
)
SELECT d.contract,
       d.first_deploy,
       MIN(m.month)    AS first_active,
       MAX(m.month)    AS last_active,
       COUNT(*)        AS active_months,
       MAX(m.callers)  AS peak_callers,
       SUM(m.calls)    AS total_calls
FROM deploys d
JOIN monthly m USING (contract)
WHERE m.callers >= @min_callers
GROUP BY d.contract, d.first_deploy
HAVING MAX(m.callers) >= @launch_min_callers
