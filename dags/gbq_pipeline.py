import json
from datetime import timedelta, datetime

from airflow import DAG
from airflow.models import Variable
from airflow.contrib.operators.bigquery_operator import BigQueryOperator
from airflow.contrib.operators.bigquery_check_operator import BigQueryCheckOperator
from airflow.sensors.external_task_sensor import ExternalTaskSensor

# GBQ Config variables

BQ_CONN_ID = "airflow-gcp"
BQ_PROJECT = "airflow-docker-352518"
BQ_DATASET = "us_curated_data"

default_args = {
    'owner': 'vanmai-airflow', 
    'depends_on_past': True,    
    'start_date': datetime(2022, 6, 1),
    'end_date': datetime(2022, 6, 10),
    'email': ['airflow@airflow.com'],
    'email_on_failure': True,
    'email_on_retry': False,
    'retries': 5,
    'retry_delay': timedelta(seconds=20),
}


# Set Schedule: Run pipeline once a day. 
# Use cron to define exact time. Eg. 8:15am would be "15 08 * * *"
schedule_interval = "00 10 * * *"

# Define DAG: Set ID and assign default args and schedule interval
dag = DAG(
    dag_id='gbq_pipeline', 
    default_args=default_args, 
    schedule_interval=schedule_interval
    )

 
# TASK 1: check if the table_id is avaiable in input dataset 
# if the quey return: False, 0, empty object, then error raised.
t1 = BigQueryCheckOperator(
        task_id='check_github',
        sql='''
        SELECT "{{ ds_nodash }}" IN 
          (
          SELECT table_id
          FROM `githubarchive.day.__TABLES_SUMMARY__`
          )
        ''',
        use_legacy_sql=False,
        bigquery_conn_id=BQ_CONN_ID,
        depends_on_past=True,
        wait_for_downstream=True,
        dag=dag
    )

# t1 Testing command: 
# docker-compose run --rm airflow-webserver airflow tasks test gbq_pipeline check_github 2022-06-02



# TASK 2: check if the data is avaiable in input dataset 
# if the quey return: False, 0, empty object, then error raised.
t2 = BigQueryCheckOperator(
        task_id='check_hackernews',
        sql='''
        SELECT "{{ ds_nodash }}" IN
            (
            SELECT FORMAT_TIMESTAMP("%Y%m%d", timestamp ) AS date
            FROM `bigquery-public-data.hacker_news.full`
            WHERE type = 'story'
            )
        ''',
        use_legacy_sql=False,
        bigquery_conn_id=BQ_CONN_ID,
        depends_on_past=True,
        wait_for_downstream=True,
        dag=dag
    )
# t2 Testing command: 
# docker-compose run --rm airflow-webserver airflow tasks test gbq_pipeline check_hackernews 2022-06-02

## Task 3: create a github daily metrics partition table
t3 = BigQueryOperator(
        task_id='write_truncate_github_agg',    
        sql='''
        with cte as
        (
          SELECT
            FORMAT_TIMESTAMP("%Y%m%d", created_at) AS date,
            actor.id as actor_id,
            CONCAT('https://github.com/', repo.name) as github_repo,
            type
          FROM
            `githubarchive.day.{{ ds_nodash }}`
        )

        SELECT
          date,
          github_repo,
          count(IF(type='WatchEvent', type, NULL)) AS subs,
          count(IF(type='PushEvent',  type, NULL)) AS pushes,
          count(IF(type='PullRequestEvent',  type, NULL)) AS pullrequests,
          count(IF(type='ForkEvent',  type, NULL)) AS copies,
          count(IF(type in ('IssueCommentEvent','CommitCommentEvent','PullRequestReviewCommentEvent'),  type, NULL)) AS comments,
          count(*) AS all_event
        FROM cte
        GROUP BY 1,2
        ORDER BY all_event desc
        ''',
        destination_dataset_table=f'{BQ_PROJECT}.{BQ_DATASET}.github_agg',
        write_disposition='WRITE_TRUNCATE',
        allow_large_results=True,
        use_legacy_sql=False,
        bigquery_conn_id=BQ_CONN_ID,
        depends_on_past=True,
        wait_for_downstream=True,
        dag=dag
    )
# t3 Testing command: 
# docker-compose run --rm airflow-webserver airflow tasks test gbq_pipeline write_truncate_github_agg 2022-06-02


# Task 5: aggregate hacker news data to a daily partition table
t5 = BigQueryOperator(
    task_id='write_truncate_hackernews_agg',    
    sql='''
    SELECT
      FORMAT_TIMESTAMP("%Y%m%d", timestamp) AS date,
      `by` AS user,
      REGEXP_EXTRACT(url, "(https?://github.com/[^/]*/[^/#?]*)") as github_repo,
      SUM(score) as score
    FROM
      `bigquery-public-data.hacker_news.full`
    WHERE TRUE
      AND FORMAT_TIMESTAMP("%Y%m%d", timestamp) = '{{ ds_nodash }}'
      AND url LIKE '%https://github.com%'
      AND url NOT LIKE '%github.com/blog/%'
    GROUP BY 1,2,3
    ''',
    destination_dataset_table=f'{BQ_PROJECT}.{BQ_DATASET}.hackernews_agg',
    write_disposition='WRITE_TRUNCATE',
    allow_large_results=True,
    use_legacy_sql=False, 
    bigquery_conn_id=BQ_CONN_ID,
    depends_on_past=True,
    wait_for_downstream=True,
    dag=dag,
    )
# t5 Testing command: 
# docker-compose run --rm airflow-webserver airflow tasks test gbq_pipeline write_truncate_hackernews_agg 2022-06-02


# Task 6: join the aggregate tables
t6 = BigQueryOperator(
    task_id='write_append_join_table',    
    sql=f'''
    SELECT 
      gh.*,
      hn.* except (date, github_repo)
    FROM
      `{BQ_PROJECT}.{BQ_DATASET}.github_agg` gh
    LEFT JOIN 
      `{BQ_PROJECT}.{BQ_DATASET}.hackernews_agg` hn
    ON hn.github_repo = gh.github_repo and hn.date = gh.date
    WHERE hn.score is not null
    ''',
    destination_dataset_table=f'{BQ_PROJECT}.{BQ_DATASET}.github_hackernews_join',
    write_disposition='WRITE_APPEND',
    allow_large_results=True,
    use_legacy_sql=False,
    bigquery_conn_id=BQ_CONN_ID,
    dag=dag
    )
# t6 Testing command: 
# docker-compose run --rm airflow-webserver airflow tasks test gbq_pipeline write_append_join_table 2022-06-02

# Task 7: Check if partition data is written successfully
t7 = BigQueryCheckOperator(
    task_id='final_check_join_table',
    sql=f'''
    SELECT "{{{{ ds_nodash }}}}" =
        (
        SELECT max(date)
        FROM `{BQ_PROJECT}.{BQ_DATASET}.github_hackernews_join`
        )
    ''',
    use_legacy_sql=False,
    bigquery_conn_id=BQ_CONN_ID,
    dag=dag)
# t6 Testing command: 
# docker-compose run --rm airflow-webserver airflow tasks test gbq_pipeline final_check_join_table 2022-06-02


# Setting Task Flow (Graph View)


t1 >> t3
t2 >> t5
[t3, t5] >> t6
t6 >> t7
 