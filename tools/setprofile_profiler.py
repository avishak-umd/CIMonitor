#!/usr/bin/env python3

import atexit
import csv
import inspect
import os
import sys
import threading
import time


# Create and Initialize Logs
profile_timestamp = time.time_ns()
step_id = os.environ.get('CINTENT_STEP_ID', 'error')

sandwich_path = os.environ.get('CINTENT_SANDWICH_LOG')
if not sandwich_path:
    log_dir = os.environ.get('CINTENT_LOGS', '/tmp')
    sandwich_path = f"{log_dir}/{profile_timestamp}.{step_id}.setprofile.sandwich.csv"
sandwich_file = open(sandwich_path, 'w')
sandwich_writer = csv.writer(sandwich_file)
sandwich = {}

graph_path = os.environ.get('CINTENT_GRAPH_LOG')
if not graph_path:
    log_dir = os.environ.get('CINTENT_LOGS', '/tmp')
    graph_path = f"{log_dir}/{profile_timestamp}.{step_id}.setprofile.graph.csv"
graph_file = open(graph_path, 'w')
graph_writer = csv.writer(graph_file)
graph = {}

# paths_path = os.environ.get('CINTENT_PATHS_LOG')
# if not paths_path:
#     log_dir = os.environ.get('CINTENT_LOGS', '/tmp')
#     paths_path = f"{log_dir}/{profile_timestamp}.{step_id}.setprofile.paths.csv"
# paths_file = open(paths_path, 'w')
# paths_writer = csv.writer(paths_file)
# paths = {}


# Get Workspace Information
_workspace = os.environ.get('GITHUB_WORKSPACE', '')
_extra = os.environ.get('CINTENT_PROJECT_PATHS', '')
_ws_prefixes = tuple(p for p in ([_workspace] + _extra.split(os.pathsep)) if p)
def _is_workspace(filename: str) -> bool:
    return bool(_ws_prefixes) and filename.startswith(_ws_prefixes)


# Initialize Utility Variables
threads = {}
write_lock = threading.Lock()
is_exiting = False
call_to_id = {} 
func_sandwich = {}


def profile_handler(frame, event, arg):
    global is_exiting
    global profile_timestamp
    global threads
    global write_lock

    if is_exiting:
        return

    if 'setprofile_profiler' in frame.f_code.co_filename:
        return
    
    if event not in ('call', 'return'):
        return

    with write_lock:
        if is_exiting:
            return

        tid = str(threading.current_thread().ident)
        if tid not in threads:
            threads[tid] = {
                "call_count": 0,
                "graph": {},
                # "paths": {},
                "stack": [],
            }
        data = threads[tid]
        
        func_name = frame.f_code.co_name
        func_path = frame.f_code.co_filename
        func_line = frame.f_code.co_firstlineno
        func_key = (func_name, func_path, func_line)

        if event in 'call':
            call_timestamp = time.time_ns()
            data["call_count"] += 1

            if func_key not in call_to_id:
                call_to_id[func_key] = len(call_to_id) + 1
            id = call_to_id[func_key]

            if id not in func_sandwich:
                code = ''
                if func_name != "<module>":
                    try:
                        code = inspect.getsource(frame)
                    except:
                        code = ''
                is_external = _ws_prefixes and not _is_workspace(frame.f_code.co_filename)
                func_sandwich[id] = {"count": 0, "duration": 0.0, "is_external": is_external, "code": code}
            func_sandwich[id]["count"] += 1

            data["stack"].append((id, call_timestamp))
        elif event in 'return':
            return_timestamp = time.time_ns()

            if not data["stack"]:
                return

            # path = tuple(data["stack"])
            # if path not in data["paths"]:
            #     data["paths"][path] = {"count": 0, "duration": 0}
            # data["paths"][path]["count"] += 1
            # data["paths"][path]["duration"] += (return_timestamp - data["stack"][0][1]) if len(path) >= 2 else (return_timestamp - profile_timestamp)

            callee = data["stack"].pop()
            duration = return_timestamp - callee[1]
            func_sandwich[callee[0]]["duration"] += duration

            if data["stack"]:
                caller = data["stack"][-1]
                
                edge = (caller[0], callee[0])
                if edge not in data["graph"]:
                    data["graph"][edge] = {"count": 0, "duration": 0}
                data["graph"][edge]["count"] += 1
                data["graph"][edge]["duration"] += duration


def cleanup():
    global is_exiting
    is_exiting = True

    # Disable Profilers
    threading.setprofile(None)
    sys.setprofile(None)

    # Write Logs to Files
    with write_lock:
        sandwich_csv = [["id", "name", "path", "line", "count", "duration_ns", "is_external", "code"]]
        graph_csv = [["src_id", "dst_id", "count", "duration_ns"]]
        # paths_csv = [["ids", "count", "duration_ns"]]

        id_to_call = {v: k for k, v in call_to_id.items()}
        sandwich_csv.extend([id, id_to_call[id][0], id_to_call[id][1], id_to_call[id][2], info["count"], info["duration"], info["is_external"], info["code"]] for id, info in func_sandwich.items())

        # Merge per-thread graphs; IDs are global, so identical edges combine
        merged = {}
        for data in threads.values():
            for edge, info in data["graph"].items():
                m = merged.setdefault(edge, {"count": 0, "duration": 0})
                m["count"] += info["count"]
                m["duration"] += info["duration"]
        graph_csv.extend([edge[0], edge[1], info["count"], info["duration"]] for edge, info in merged.items())

        sandwich_writer.writerows(sandwich_csv)
        graph_writer.writerows(graph_csv)

            # paths_csv.extend(["->".join(str(node[0]) for node in chain), info["count"], info["duration"]] for chain, info in data["paths"].items())
            # paths_writer.writerows(paths_csv)

        sandwich_file.close()
        graph_file.close() 
        # paths_file.close()
    
        func_count = len(sandwich_csv) - 1
        call_count = sum(entry[2] for entry in graph_csv[1:]) if len(graph_csv) >= 2 else 0
        # path_count = sum(entry[1] for entry in paths_csv[1:]) if len(paths_csv) >= 2 else 0
        # print(f"[setprofile] Captured {func_count} functions to {sandwich_path}, {call_count} calls to {graph_path}, and {path_count} paths to {paths_path}", file=sys.stderr)
        print(f"[setprofile] Captured {func_count} functions to {sandwich_path} and {call_count} calls to {graph_path}", file=sys.stderr)


# Register cleanup
atexit.register(cleanup)

# Register profiler for the current thread and all future threads
threading.setprofile(profile_handler)
sys.setprofile(profile_handler)

# print(f"[setprofile] Profiling enabled, logging functions to {sandwich_path}, calls to {graph_path}, and call paths to {paths_path}", file=sys.stderr)
print(f"[setprofile] Profiling enabled, logging functions to {sandwich_path} and calls to {graph_path}", file=sys.stderr)
