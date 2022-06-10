
from datetime import timedelta

import airflow
from airflow import DAG
from airflow.operators.bash_operator import BashOperator

# These args will get passed on to each operator
# You can override them on a per-task basis during operator initialization
default_args = {
    'owner': 'vanmai',
    'depends_on_past': False,
    'start_date': airflow.utils.dates.days_ago(15),
    'email': ['airflow@example.com'],
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
    # 'queue': 'bash_queue',
    # 'pool': 'backfill',
    # 'priority_weight': 10,
    # 'end_date': datetime(2016, 1, 1),
    # 'wait_for_downstream': False,
    # 'dag': dag,
    # 'adhoc':False,
    # 'sla': timedelta(hours=2),
    # 'execution_timeout': timedelta(seconds=300),
    # 'on_failure_callback': some_function,
    # 'on_success_callback': some_other_function,
    # 'on_retry_callback': another_function,
    # 'trigger_rule': u'all_success'
}

dag = DAG(
    'vanmai-demo',
    default_args=default_args,
    description='van DAG',
    schedule_interval=timedelta(days=1),
)

# t1, t2 and t3 are examples of tasks created by instantiating operators
t1 = BashOperator(
    task_id='t1_print_date',
    bash_command='date',
    dag=dag,
)


t2 = BashOperator(
    task_id='t2_sleep_5s',
    depends_on_past=False,
    bash_command='sleep 5',
    dag=dag,
)

templated_command = """
{% for i in range(5) %}
    echo "{{ ds }}"
    echo "{{ macros.ds_add(ds, 7)}}"
    echo "{{ params.my_param }}"
{% endfor %}
"""

t3 = BashOperator(
    task_id='t3_templated',
    depends_on_past=False,
    bash_command=templated_command,
    params={'my_param': 'Parameter I passed in'},
    dag=dag,
)

t4 = BashOperator(
    task_id='t4_done',
    depends_on_past=False,
    bash_command='echo Done',
    dag=dag,
)


t1 >> [t2, t3] 

[t2, t3]  >> t4


#[t2, t3] << t1

# t1 << t2
# t2 << t3

