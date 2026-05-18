/*
WITH all_labels AS (

    SELECT 'additional_tags' AS source_column, NULLIF(TRIM(v::text), '') AS raw_value
    FROM ngp_call_classification
    CROSS JOIN LATERAL unnest(additional_tags) AS v
    WHERE additional_tags IS NOT NULL
      AND NULLIF(TRIM(v::text), '') IS NOT NULL

    UNION ALL
    SELECT 'descriptive_keywords' AS source_column, NULLIF(TRIM(v::text), '') AS raw_value
    FROM ngp_call_classification
    CROSS JOIN LATERAL unnest(descriptive_keywords) AS v
    WHERE descriptive_keywords IS NOT NULL
      AND NULLIF(TRIM(v::text), '') IS NOT NULL

    UNION ALL
    SELECT 'coaching_tags' AS source_column, NULLIF(TRIM(v::text), '') AS raw_value
    FROM ngp_call_classification
    CROSS JOIN LATERAL unnest(coaching_tags) AS v
    WHERE coaching_tags IS NOT NULL
      AND NULLIF(TRIM(v::text), '') IS NOT NULL

    UNION ALL
    SELECT 'tags' AS source_column, NULLIF(TRIM(v::text), '') AS raw_value
    FROM ngp_call_classification
    CROSS JOIN LATERAL unnest(tags) AS v
    WHERE tags IS NOT NULL
      AND NULLIF(TRIM(v::text), '') IS NOT NULL

    UNION ALL
    SELECT 'main_reason' AS source_column, NULLIF(TRIM(main_reason::text), '') AS raw_value
    FROM ngp_call_classification
    WHERE main_reason IS NOT NULL
      AND NULLIF(TRIM(main_reason::text), '') IS NOT NULL

    UNION ALL
    SELECT 'call_type' AS source_column, NULLIF(TRIM(call_type::text), '') AS raw_value
    FROM ngp_call_classification
    WHERE call_type IS NOT NULL
      AND NULLIF(TRIM(call_type::text), '') IS NOT NULL

    UNION ALL
    SELECT 'outcome_sub' AS source_column, NULLIF(TRIM(outcome_sub::text), '') AS raw_value
    FROM ngp_call_classification
    WHERE outcome_sub IS NOT NULL
      AND NULLIF(TRIM(outcome_sub::text), '') IS NOT NULL

    UNION ALL
    SELECT 'call_type_sub' AS source_column, NULLIF(TRIM(call_type_sub::text), '') AS raw_value
    FROM ngp_call_classification
    WHERE call_type_sub IS NOT NULL
      AND NULLIF(TRIM(call_type_sub::text), '') IS NOT NULL

    UNION ALL
    SELECT 'outcome' AS source_column, NULLIF(TRIM(outcome::text), '') AS raw_value
    FROM ngp_call_classification
    WHERE outcome IS NOT NULL
      AND NULLIF(TRIM(outcome::text), '') IS NOT NULL

    UNION ALL
    SELECT 'next_step' AS source_column, NULLIF(TRIM(next_step::text), '') AS raw_value
    FROM ngp_call_classification
    WHERE next_step IS NOT NULL
      AND NULLIF(TRIM(next_step::text), '') IS NOT NULL

    UNION ALL
    SELECT 'tone' AS source_column, NULLIF(TRIM(tone::text), '') AS raw_value
    FROM ngp_call_classification
    WHERE tone IS NOT NULL
      AND NULLIF(TRIM(tone::text), '') IS NOT NULL

    UNION ALL
    SELECT 'outcome_base' AS source_column, NULLIF(TRIM(outcome_base::text), '') AS raw_value
    FROM ngp_call_classification
    WHERE outcome_base IS NOT NULL
      AND NULLIF(TRIM(outcome_base::text), '') IS NOT NULL

    UNION ALL
    SELECT 'call_type_base' AS source_column, NULLIF(TRIM(call_type_base::text), '') AS raw_value
    FROM ngp_call_classification
    WHERE call_type_base IS NOT NULL
      AND NULLIF(TRIM(call_type_base::text), '') IS NOT NULL
)
SELECT
    source_column,
    raw_value,
    COUNT(*) AS value_count
FROM all_labels
GROUP BY source_column, raw_value
ORDER BY source_column, value_count DESC;
*/



WITH all_labels AS (
    SELECT 'additional_tags' AS source_column, NULLIF(TRIM(v::text), '') AS raw_value
    FROM ngp_call_classification
    CROSS JOIN LATERAL unnest(additional_tags) AS v
    WHERE additional_tags IS NOT NULL
    AND NULLIF(TRIM(v::text), '') IS NOT NULL
)
SELECT
    source_column,
    raw_value,
    COUNT(*) AS value_count
FROM all_labels
GROUP BY source_column, raw_value
ORDER BY value_count DESC;


