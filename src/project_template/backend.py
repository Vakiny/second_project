import pandas as pd
import matplotlib.pyplot as plt
import streamlit as st

class Backend():
    def demo_age_group(self):
        return """
            SELECT 
                CASE 
                    WHEN c.age < 40 THEN 'Younger (Under 40)'
                    WHEN c.age BETWEEN 40 AND 60 THEN 'Middle-aged (40-60)'
                    ELSE 'Older (60+)' 
                END AS age_group,
                SUM(cv.num_visits) AS total_visits
            FROM view_client_visits cv
            JOIN clients c ON c.id = cv.client_id
            GROUP BY age_group
            ORDER BY total_visits DESC;
        """, pd.read_csv("./data/sql/output/demographics/age_groups.csv")

    def demo_tenure(self):
        return """
            SELECT 
                CASE 
                    WHEN c.tenure_years < 3 THEN 'New (1-2 year)'
                    WHEN c.tenure_years < 5 THEN 'Moderately long (3-4 years)'
                    ELSE 'Long-standing (5+ years)' 
                END AS tenure_group,
                SUM(cv.num_visits) AS total_visits
            FROM view_client_visits cv
            JOIN clients c ON c.id = cv.client_id
            GROUP BY tenure_group
            ORDER BY total_visits DESC;
        """, pd.read_csv("./data/sql/output/demographics/tenure.csv")

    def latest_visits(self):
        return """
            CREATE OR REPLACE VIEW latest_visits AS (
                SELECT
                    client_id,
                    visitor_id,
                    visit_id,
                    process_step,
                    MAX(date_time) AS last_date_time
                FROM client_visits
                GROUP BY client_id, visitor_id, visit_id, process_step
            );
        """

    def completion_rate(self):
        return """
            WITH cte_distinct_client_stats AS (
                SELECT
                    ce.variation,
                    COUNT(
                            DISTINCT CASE
                                WHEN process_step = 'confirm'
                                THEN lv.client_id
                            END
                        ) AS completed_clients,
                    COUNT(DISTINCT lv.client_id) AS total_clients
                FROM latest_visits lv
                JOIN client_experiments ce ON ce.client_id = lv.client_id
                GROUP BY ce.variation
            )
            SELECT
                completed_clients,
                total_clients,
                ROUND(100 * completed_clients / total_clients, 2) AS percentage
            FROM cte_distinct_client_stats
            ORDER BY variation="Test", variation="Control";
        """, pd.read_csv("./data/sql/output/visit_kpis/completion_rate_percentage.csv")

    def step_completion_rate(self):
        return """
            WITH cte_step_counts AS (
                SELECT 
                    ce.variation,
                    lv.process_step,
                    COUNT(DISTINCT lv.client_id, lv.visitor_id, lv.visit_id) AS num_visits
                FROM latest_visits lv
                JOIN client_experiments ce ON ce.client_id = lv.client_id
                GROUP BY ce.variation, lv.process_step
            ),
            cte_total_visits AS (
                SELECT 
                    ce.variation,
                    COUNT(DISTINCT lv.client_id, lv.visitor_id, lv.visit_id) AS total_visits
                FROM latest_visits lv
                JOIN client_experiments ce ON ce.client_id = lv.client_id
                WHERE lv.process_step = 'start'
                GROUP BY ce.variation
            )
            SELECT 
                sc.variation,
                sc.process_step,
                ROUND(sc.num_visits * 100.0 / tv.total_visits, 2) AS percentage
            FROM cte_step_counts sc
            JOIN cte_total_visits tv ON sc.variation = tv.variation
            ORDER BY FIELD(sc.variation, "Control", "Test"),
                    FIELD(sc.process_step, "start", "step_1", "step_2", "step_3", "confirm");
        """, pd.read_csv("./data/sql/output/visit_kpis/step_completation_rate_percentage.csv")

    def average_step_duration(self):
        return """
            WITH cte_step_durations AS (
                SELECT
                    ce.variation,
                    lv.client_id,
                    lv.visitor_id,
                    lv.visit_id,
                    lv.process_step,
                    lv.last_date_time,
                    TIMESTAMPDIFF(
                        SECOND,
                        LAG(lv.last_date_time) OVER (
                            PARTITION BY lv.client_id, lv.visitor_id, lv.visit_id 
                            ORDER BY lv.last_date_time
                        ),
                        lv.last_date_time
                    ) AS time_spent_seconds
                FROM latest_visits lv
                JOIN client_experiments ce ON ce.client_id = lv.client_id
            )
            SELECT 
                variation,
                process_step,
                COUNT(*) AS num_visits,
                ROUND(AVG(time_spent_seconds), 2) AS avg_time_seconds
            FROM cte_step_durations
            WHERE
                time_spent_seconds IS NOT NULL
                AND process_step <> "start"
            GROUP BY variation, process_step
            ORDER BY
                FIELD(variation, "Control", "Test"), 
                FIELD(process_step, 'start', 'step_1', 'step_2', 'step_3', 'confirm');
    """, pd.read_csv("./data/sql/output/visit_kpis/average_time_per_step.csv")

    def error_rate_percentage(self):
        return """
            WITH
            cte_step_orders AS (
                SELECT 
                    lv.client_id, 
                    lv.visitor_id, 
                    lv.visit_id, 
                    ce.variation,
                    lv.process_step, 
                    lv.last_date_time,
                    ROW_NUMBER() OVER (
                        PARTITION BY lv.client_id, lv.visitor_id, lv.visit_id 
                        ORDER BY lv.last_date_time
                    ) AS step_order,
                    CASE 
                        WHEN lv.process_step = 'start' THEN 1
                        WHEN lv.process_step = 'step_1' THEN 2
                        WHEN lv.process_step = 'step_2' THEN 3
                        WHEN lv.process_step = 'step_3' THEN 4
                        WHEN lv.process_step = 'confirm' THEN 5
                        ELSE NULL
                    END AS step_rank
                FROM latest_visits lv
                JOIN client_experiments ce ON lv.client_id = ce.client_id
            ),
            cte_transitions AS (
                SELECT 
                    a.variation,
                    a.process_step AS current_step,
                    b.process_step AS previous_step,
                    CASE 
                        WHEN b.step_rank = a.step_rank + 1 THEN 1
                        ELSE 0 
                    END AS is_backward_transition
                FROM cte_step_orders a
                LEFT JOIN cte_step_orders b 
                    ON a.visit_id = b.visit_id AND a.step_order = b.step_order + 1
            ),
            cte_error_counts AS (
                SELECT 
                    variation,
                    COUNT(*) - 1 AS total_transitions,
                    SUM(is_backward_transition) AS backward_transitions
                FROM cte_transitions
                WHERE previous_step IS NOT NULL
                GROUP BY variation
            )
            SELECT
                variation,
                ROUND(100.0 * backward_transitions / total_transitions, 2) AS percentage
            FROM cte_error_counts
            ORDER BY variation;
        """, pd.read_csv("./data/sql/output/visit_kpis/error_rate_percentage.csv")

    def plot_step_average_time(self, test=False):
        variation = "Test" if test else "Control"

        df = pd.read_csv("./data/sql/output/visit_kpis/average_time_per_step.csv")
        average_time = df[df["variation"] == variation]
       
        plt.figure(figsize=(10, 5))
        plt.bar(
            average_time["process_step"],
            average_time["avg_time_seconds"],
            label=variation,
            color="red" if test else "blue"
        )
        for i, value in enumerate(average_time["avg_time_seconds"]):
            plt.text(i, value, str(value), ha='center', va='bottom')
        plt.title(variation)
        plt.xlabel("Step")
        plt.ylabel("Average Time (s)")
        plt.xticks(rotation=45)
        plt.tight_layout()
        st.pyplot(plt)

    def plot_step_completion_rate(self, test=False):
        variation = "Test" if test else "Control"

        df = pd.read_csv("./data/sql/output/visit_kpis/step_completation_rate_percentage.csv")
        step_completion_rate = df[df["variation"] == variation]

        plt.figure(figsize=(10, 5))
        plt.bar(
            step_completion_rate["process_step"],
            step_completion_rate["percentage"],
            label=variation,
            color="red" if test else "blue"
        )
        for i, value in enumerate(step_completion_rate["percentage"]):
            plt.text(i, value, str(value), ha='center', va='bottom')
        plt.title(variation)
        plt.xlabel("Step")
        plt.ylabel("Completion Rate")
        plt.xticks(rotation=45)
        plt.tight_layout()
        st.pyplot(plt)
