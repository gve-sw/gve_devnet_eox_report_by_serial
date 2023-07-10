#!/usr/bin/env python3
"""
Copyright (c) 2023 Cisco and/or its affiliates.
This software is licensed to you under the terms of the Cisco Sample
Code License, Version 1.1 (the "License"). You may obtain a copy of the
License at
https://developer.cisco.com/docs/licenses
All use of the material herein must be in accordance with the terms of
the License. All rights not expressly granted by the License are
reserved. Unless required by applicable law or agreed to separately in
writing, software distributed under the License is distributed on an "AS
IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express
or implied.
"""

__author__ = "Trevor Maco <tmaco@cisco.com>, Jorge Banegas <jbanegas@cisco.com>"
__copyright__ = "Copyright (c) 2023 Cisco and/or its affiliates."
__license__ = "Cisco Sample Code License, Version 1.1"

import datetime
import json
import math
import re

import pandas as pd
import requests
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress

import config

# Rich Console Instance
console = Console()


def access_token_request():
    """
    Get Access Token for EoX API (see README to ensure proper access to API and the creation of an App)
    :return: EoX Access Token
    """
    url = "https://id.cisco.com/oauth2/default/v1/token"
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    payload = {
        "client_id": config.CLIENT_ID,
        "client_secret": config.CLIENT_SECRET,
        "grant_type": "client_credentials",
    }

    response = requests.post(url=url, headers=headers, data=payload)

    if response.ok:
        json_resp = json.loads(response.text)
        return json_resp["access_token"]
    else:
        response.raise_for_status()


def send_eox_by_serial_request(token, product_serial_chunk):
    """
    Retrieve EoX Dates based on Serial
    :param token: EoX API Token
    :param product_serial_chunk: A Group of Product Serials
    :return: EoX Date(s)
    """
    url = "https://apix.cisco.com/supporttools/eox/rest/5/EOXBySerialNumber/1/"

    # remove any serials which don't match the correct format of Cisco Serials
    filtered_product_serial_chunk = filter_strings(product_serial_chunk)

    eol_url = f'{url}{",".join(filtered_product_serial_chunk)}'

    headers = {
        'Authorization': 'Bearer {}'.format(token),
    }
    payload = {}

    response = requests.get(url=eol_url, headers=headers, data=payload)
    if response.ok:
        eox_data = json.loads(response.text)
        try:
            # Extract the required information from the response and return it
            return eox_data['EOXRecord']
        except KeyError:
            return None
    else:
        return None


def chunker(seq, size):
    """
    Splits Serial column into chunks of size (where 'size' is the maximum value of serials we can simultaneously process)
    :param seq: Sequence of Serials
    :param size: Max partition size
    :return: List of serial partitions
    """
    return (seq[pos:pos + size] for pos in range(0, len(seq), size))


def filter_strings(lst):
    """
    Remove all Serials which are invalid Cisco Serials (larger than 40 characters, blank, non alphanumeric characters, etc.)
    :param lst: Serial list
    :return: Clean list of valid Serials
    """
    filtered_lst = [s for s in lst if len(s) <= 40 and re.match(r'^[a-zA-Z0-9]+$', s)]
    return filtered_lst


def get_eox_data(access_token, serial_df):
    """
    Process Serials, build dictionaries containing EOX dates per serial
    :param access_token: EoX API Token
    :param serial_df: Dataframe containing all serials
    :return: List of EoX data dictionaries per serial
    """
    # Break List of Serials into Chunks of 20 (maximum supported by API for simultaneous query)
    product_serial_chunker = chunker(serial_df, 20)
    chunk_count = math.ceil(len(serial_df.index) / 20)

    console.print(f'Divided Serial list into [blue]{chunk_count} chunks[/]')
    with Progress() as progress:
        overall_progress = progress.add_task("Overall Progress", total=chunk_count, transient=True)
        counter = 1

        eox_info = []
        chunker_index = 0
        # Iterate through each chunk of 20 serials
        for product_serial_chunk in product_serial_chunker:
            chunker_index = chunker_index + 1

            # Get EoX data for each chunk of serials
            product_serial_chunk_list = product_serial_chunk[config.SERIAL_NUMBER_COLUMN_NAME].astype(str).tolist()
            eox_record_list = send_eox_by_serial_request(access_token, product_serial_chunk_list)

            progress.console.print(
                "Processing Serials: {} (Chunk {} of {})".format(product_serial_chunk_list,
                                                                 str(counter), chunk_count))

            if eox_record_list:
                for eox_record in eox_record_list:
                    entry_serials = eox_record['EOXInputValue'].split(',')

                    # The same entry may be returned for multiple serials, iterate and create a new entry for each serial
                    for entry_serial in entry_serials:
                        eol_date_dict = {config.SERIAL_NUMBER_COLUMN_NAME: entry_serial, 'End Of Sale Date': '',
                                         'End Of SW Maintenance Releases': '',
                                         'End Of Routine Failure Analysis Date': '',
                                         'End Of Security Vulnerability Support Date': '', 'Last Date Of Support': ''}

                        # Extract and add relevant dates to EoX entry (convert date format, ignore empty values)
                        if 'EndOfSaleDate' in eox_record and eox_record['EndOfSaleDate']['value'] != '':
                            date = datetime.datetime.strptime(eox_record['EndOfSaleDate']['value'],
                                                              "%Y-%m-%d").strftime(
                                "%m/%d/%Y")
                            eol_date_dict['End Of Sale Date'] = date

                        if 'EndOfSWMaintenanceReleases' in eox_record and eox_record['EndOfSWMaintenanceReleases'][
                            'value'] != '':
                            date = datetime.datetime.strptime(eox_record['EndOfSWMaintenanceReleases']['value'],
                                                              "%Y-%m-%d").strftime("%m/%d/%Y")
                            eol_date_dict['End Of SW Maintenance Releases'] = date

                        if 'EndOfRoutineFailureAnalysisDate' in eox_record and \
                                eox_record['EndOfRoutineFailureAnalysisDate']['value'] != '':
                            date = datetime.datetime.strptime(eox_record['EndOfRoutineFailureAnalysisDate']['value'],
                                                              "%Y-%m-%d").strftime("%m/%d/%Y")
                            eol_date_dict['End Of Routine Failure Analysis Date'] = date

                        if 'EndOfSecurityVulSupportDate' in eox_record and eox_record['EndOfSecurityVulSupportDate'][
                            'value'] != '':
                            date = datetime.datetime.strptime(eox_record['EndOfSecurityVulSupportDate']['value'],
                                                              "%Y-%m-%d").strftime("%m/%d/%Y")
                            eol_date_dict['End Of Security Vulnerability Support Date'] = date

                        if 'LastDateOfSupport' in eox_record and eox_record['LastDateOfSupport']['value'] != '':
                            date = datetime.datetime.strptime(eox_record['LastDateOfSupport']['value'],
                                                              "%Y-%m-%d").strftime("%m/%d/%Y")
                            eol_date_dict['Last Date Of Support'] = date

                        eox_info.append(eol_date_dict)

            counter += 1
            progress.update(overall_progress, advance=1)

    return eox_info


def main():
    console.print(Panel.fit("EoX Report by Serial"))

    # Request EoX API Access Token
    console.print(Panel.fit("GET EoX Access Token", title="Step 1"))
    access_token = access_token_request()

    console.print("[green]Obtained Access Token for EoX API[/]")

    # Read in CSV File (make sure minimum Serial Number column is present!)
    data_df = pd.read_csv(config.CSV_FILE_NAME)

    console.print(Panel.fit("Process Serials from CSV File", title="Step 2"))

    # Get EoX Data for Serial List
    new_eox_list = get_eox_data(access_token, data_df)

    # Build new DF mapping Serial to EoX date field
    new_eox_df = pd.DataFrame(new_eox_list)

    # Merge new DF with original dataset using Serial column
    temp_new_eox_df = data_df.merge(new_eox_df, on=[config.SERIAL_NUMBER_COLUMN_NAME], how='left')

    # Write Dataframe to output CSV
    output_file_name = config.CSV_FILE_NAME.split('.')[0] + '_output.csv'
    temp_new_eox_df.to_csv(output_file_name)

    console.print(f'[green]Successfully wrote EoX data to {output_file_name}![/]')


if __name__ == "__main__":
    main()
