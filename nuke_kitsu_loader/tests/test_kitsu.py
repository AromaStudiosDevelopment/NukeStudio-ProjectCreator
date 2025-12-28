import gazu
import pprint
import re
from cert_utils import configure_kitsu_ca_bundle

# Kitsu server with self-signed certificate
host = "https://192.168.150.179/api"
configure_kitsu_ca_bundle(host)
gazu.set_host(host)
gazu.log_in("ahmed.ramadan@aromastudios.net", "12345678")

task_types = ["Compositing", "Roto_Keying", "Cleanup"]

project = gazu.project.get_project_by_name("Sameh_20250914")
all_sequences = gazu.shot.all_sequences_for_project(project)
for seq in all_sequences:   #fetching all sequences shots tasks 
    # print("Sequence: ", seq['name'])
    all_shots = gazu.shot.all_shots_for_sequence(seq)
    for shot in all_shots:
        # all tasks for shots
        all_tasks = gazu.task.all_tasks_for_shot(shot)
        for task in all_tasks:
            #TODO if task["task_type_name"] in task_types:    #ensuring 2D task types
            comments = gazu.task.all_comments_for_task(task)
            if task['task_type_name'] == 'Conforming':
                for comment in comments:
                    comment_text = comment["text"]
                    location_pattern = r"location.*?`([^`]+)`"
                    match = re.search(location_pattern, comment_text, re.IGNORECASE | re.DOTALL)
                    if match:
                        extracted_location = match.group(1)
                        print(f"Shot: {shot['name']}, Task: {task['task_type_name']}, Location: {extracted_location}")
                    print("*"*20)
            if task['task_type_name'] == 'Compositing':
                for comment in comments:
                    comment_text = comment["text"]
                    location_pattern = r"location.*?`([^`]+)`"
                    Workfile_pattern = r"Workfile.*?`([^`]+)`"
                    match = re.search(location_pattern, comment_text, re.IGNORECASE | re.DOTALL)
                    workfile_match = re.search(Workfile_pattern, comment_text, re.IGNORECASE | re.DOTALL)
                    if match:
                        extracted_location = match.group(1)
                        extracted_workfile = workfile_match.group(1) if workfile_match else "N/A"
                        print(f"Shot: {shot['name']}, Task: {task['task_type_name']}, Location: {extracted_location}", "Workfile: ", extracted_workfile)
                    print("*"*20)
    break