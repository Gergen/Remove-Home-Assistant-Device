#! /usr/bin/env python3

import json
import codecs
import sys
from colorama  import init, Fore
init(autoreset = True)

from typing import List, Dict
import argparse

parser = argparse.ArgumentParser(description="""Delete device and dependent items from config files. 
             Ensure you copy 'core.entity_registry', 'core.device_registry' and 'core.config_entries'
             to the folder where you are running this script.
             """)
parser.add_argument('--name', type=str, help="Name of device to delete.")
parser.add_argument('--id', type=str, help=" Id of device to delete.")
args = parser.parse_args()

if args.name:
    delete_by_name = args.name
    print(Fore.GREEN + f"Deleting the device named \"{delete_by_name}\".")
else:
    delete_by_name = ""
if args.id:
    delete_by_id = args.id
    print(Fore.GREEN + f"Deleting the device with id \"{delete_by_id}\" (any given name will be ignored).")
else:
    delete_by_id = ""
if not( delete_by_name or delete_by_id ):
    parser.print_help()
    sys.exit(1)

def list_without_indexes(original: List, id_list: List[str], index_by_id: Dict[str, int]):
    new = []
    i_set = set([index_by_id[id] for id in id_list])
    for i in range(len(original)):
        if i not in i_set:
            new.append(original[i])
    return new


def from_json_file(file_name: str) -> Dict:
    with codecs.open(file_name, "r", "utf-8-sig") as file:
        return json.load(file)


def to_json_file(file_name: str, data: Dict):
    with open(file_name, "w", encoding="utf-8") as outfile:
        json.dump(data, outfile, ensure_ascii=False, indent=4)


core_config_entries = from_json_file("core.config_entries")
config_entries = core_config_entries["data"]["entries"]
core_entity_registry = from_json_file("core.entity_registry")
entities = core_entity_registry["data"]["entities"]
core_device_registry = from_json_file("core.device_registry")
devices = core_device_registry["data"]["devices"]

# configs have "entry_id"
config_entry_index_by_entry_id = {config_entries[i]["entry_id"]: i for i in range(len(config_entries))}

# devices have "name" and "id"
# - there is "name_by_user" on some devices
# - may be loaded "via_device_id"
# - may have "config_entries" (a list of ids)
# - may have "disabled_by": (null | "user"),
device_index_by_id = {devices[i]["id"]: i for i in range(len(devices))}
print(f"Found {len(device_index_by_id)} devices by id.")

# dict of device by id (populated when we build the device_ids_by_name dict)
device_by_id = {}

# device_ids_by_name = {device["name"]: device["id"] for device in devices}
device_ids_by_name = {}
duplicate_names = {} # only for names that occur more than once, dict of lists, key = device name, value = list of ids
for device in devices:
    name = device["name"]
    id = device["id"]
    device_by_id[ id ] = device
    if name in device_ids_by_name:
        existing_id = device_ids_by_name[ name ]
        existing_device = device_by_id[ existing_id ] 
        if name not in duplicate_names:
            duplicate_names[ name ] = [ existing_device['id'] ]
        duplicate_names[ name ].append( id)
    device_ids_by_name[ name ] = id
print(f"Found {len(device_ids_by_name)} devices by unique name.")


if duplicate_names:
    print(Fore.YELLOW + f"WARNING: You have multiple devices with the same name.")
    print(Fore.YELLOW + f"{'name':>30} {'id':>40} {'connections'}")
    for name, ids in duplicate_names.items():
        for id in ids:
            device = device_by_id[ id ]
            print(Fore.YELLOW + f"{repr(name):>30} {device['id']:>40} {device['connections']}")

device_ids_by_name_by_user = {device["name_by_user"]: device["id"] for device in devices if device["name_by_user"] is not None}
print(f"Found {len(device_ids_by_name_by_user)} devices by name by user.")

if delete_by_name and (delete_by_name in duplicate_names):
    print(Fore.RED + f"ERROR: You asked for deletion by a name of a name that is not unique. That is not possible. Aborting.")
    sys.exit(1)

# index the devices by config id to see if there are any configs referenced by multiple devices
device_ids_by_config_entry_id = {}
for device in devices:
    for config_entry_id in device["config_entries"]:
        if config_entry_id not in device_ids_by_config_entry_id:
            device_ids_by_config_entry_id[config_entry_id] = set()
        device_ids_by_config_entry_id[config_entry_id].add(device["id"])
for config_entry, device_id_set in device_ids_by_config_entry_id.items():
    if len(device_id_set) > 1:
        print(f"config_entry \"{config_entry}\" is referenced from {len(device_id_set)} devices")

# build the tree of device dependencies, as far as I can see, each device can only have one parent
# so there's no possibility of replication or loops
device_ids_by_parent_id = {}
for device in devices:
    via_device_id = device["via_device_id"]
    if via_device_id is not None:
        if via_device_id not in device_ids_by_parent_id:
            device_ids_by_parent_id[via_device_id] = []
        device_ids_by_parent_id[via_device_id].append(device["id"])


def get_device_id_list(device_id: str):
    # descend the tree recursively
    def internal(device_id: str, to_list: List[str]):
        to_list.append(device_id)
        if device_id in device_ids_by_parent_id:
            for child_device_id in device_ids_by_parent_id[device_id]:
                internal(child_device_id, to_list)
        return to_list
    return internal(device_id, [])


# entities are attached to a "device_id"
# - may have "disabled_by": (null | "integration")
entity_index_by_id = {entities[i]["id"]: i for i in range(len(entities))}
entity_ids_by_device_id = {}
for i in range(len(entities)):
    entity = entities[i]
    device_id = entity["device_id"]
    if device_id not in entity_ids_by_device_id:
        entity_ids_by_device_id[device_id] = set()
    entity_ids_by_device_id[device_id].add(entity["id"])

# search the device we want to delete

target_device_id = None
if delete_by_id:
    if delete_by_id in device_by_id:
        target_device_id = delete_by_id
else:
    if delete_by_name in device_ids_by_name:
        target_device_id = device_ids_by_name[delete_by_name]
    if (target_device_id is None) and (delete_by_name in device_ids_by_name_by_user):
       target_device_id = device_ids_by_name_by_user[delete_by_name]
# if we identified a target device...
if target_device_id is not None:
    # gather the full list of devices and dependencies to remove
    device_id_list = get_device_id_list(target_device_id)
    print("Devices to remove:")
    print([device_id + " - " + devices[device_index_by_id[device_id]]["name"] for device_id in device_id_list])

    # gather the full list of config entries to be removed
    for device_id in device_id_list:
        device = devices[device_index_by_id[device_id]]
        for config_entry_id in device["config_entries"]:
            if config_entry_id in device_ids_by_config_entry_id:
                device_ids_by_config_entry_id[config_entry_id].remove(device_id)
    config_entry_id_list = []
    for config_entry_id in device_ids_by_config_entry_id.keys():
        if len(device_ids_by_config_entry_id[config_entry_id]) == 0:
            config_entry_id_list.append(config_entry_id)
    print("Config Entries to remove:")
    print([config_entry_id + " - " + config_entries[config_entry_index_by_entry_id[config_entry_id]]["title"] for config_entry_id in config_entry_id_list])

    # gather the full list of entities to remove
    entity_id_list = []
    for device_id in device_id_list:
        if device_id in entity_ids_by_device_id:
            entity_id_list.extend(entity_ids_by_device_id[device_id])
    print("Entities to remove:")
    # note: some entities have no 'name' although they all do seem to have an 'original_name' 
    print([entity_id + " - " + str(entities[entity_index_by_id[entity_id]]["original_name"]) for entity_id in entity_id_list])

    # now actually remove the elements
    devices = list_without_indexes(devices, device_id_list, device_index_by_id)
    config_entries = list_without_indexes(config_entries, config_entry_id_list, config_entry_index_by_entry_id)
    entities = list_without_indexes(entities, entity_id_list, entity_index_by_id)

    # restore them to their places in their respective documents
    core_config_entries["data"]["entries"] = config_entries
    core_entity_registry["data"]["entities"] = entities
    core_device_registry["data"]["devices"] = devices

    # and save them out as new files
    to_json_file("core.config_entries", core_config_entries)
    to_json_file("core.entity_registry", core_entity_registry)
    to_json_file("core.device_registry", core_device_registry)
    print(Fore.GREEN + "DONE.")
else:
    print(Fore.RED + "ERROR: No such device. Nothing to delete.")
    sys.exit(1)
    