#!/usr/bin/env python

import numpy as np
import pandas as pd
import requests
import time
from bs4 import BeautifulSoup
import re
from tqdm import tqdm
from astropy.coordinates import SkyCoord
from astropy.coordinates import Angle
from astroquery.ned import Ned
from astropy import units as u
from pathlib import Path
from time import sleep
import matplotlib.pyplot as plt
import utils

C = 3.e5 # km/s
H_0 = 70. # km/s/Mpc
OMEGA_M = 0.3
OMEGA_V = 0.7
WMAP = 4
CORR_Z = 1
QUERY_RADIUS = 5. # arcmin
BLOCK_SIZE = 10
NED_RESULTS_FILE = Path('out/scraped_table.csv')
NED_RESULTS_FILE_TMP = Path('out/scraped_table-tmp.csv')
BIB_FILE = Path('out/table_references.bib')
CAT_FILE = Path('out/catalog_codes.txt')
LATEX_TABLE_TEMPLATE = Path('ref/deluxetable_template.tex')
LATEX_TABLE_FILE = Path('out/table.tex')
SHORT_TABLE_FILE = Path('out/short_table.tex')


def main():

    fits_info = pd.read_csv('out/fitsinfo.csv', index_col='Name')
    sn_info = compress_duplicates(fits_info)
    ref = pd.read_csv('ref/OSC-pre2014-v2-clean.csv', index_col='Name')

    prev = 'o'
    if NED_RESULTS_FILE.is_file():
        prev = input('Previous NED query results found. [K]eep/[c]ontinue/[o]verwrite? ')

    # Overwrite completely
    if prev == 'o':
        ned = pd.DataFrame()
        sne = np.array(sn_info.index)
    # Continue from previous output
    elif prev == 'c':
        ned = pd.read_csv(NED_RESULTS_FILE, index_col='name', dtype={'z':float, 'h_dist':float})
        sne = np.array([row.name for i, row in sn_info.iterrows() if row.name not in ned.index])
    # Keep previous output
    else:
        ned = pd.read_csv(NED_RESULTS_FILE, index_col='name', dtype={'z':float, 'h_dist':float})
        sne = np.array([])

    blocks = np.arange(0, len(sne), BLOCK_SIZE)
    for b in tqdm(blocks):
        sample = sne[b:min(b+BLOCK_SIZE, len(sne))]
        block = pd.concat([get_sn(sn, sn_info, ref, verb=0) for sn in sample])
        ned = pd.concat([ned, block])
        utils.output_csv(ned, NED_RESULTS_FILE)

    #plot_redshifts(ned)
    to_latex(ned, sn_info)


def get_sn(sn, fits_info, ref, verb=0):
    """
    Retrieve SN info from NED. Uses astroquery to retrieve target names, then
    web scrapes to get target info.
    Inputs:
        sn (str): SN name
        fits_info (DataFrame): FITS file info, with duplicate entries removed
        ref (DataFrame): SN reference info, e.g. from OSC
        verb (int or bool, optional): vebrose output? default: False
    Output:
        sn_info (DataFrame): web-scraped info from NED
    """

    host = ref.loc[sn, 'Host Name']
    ra, dec = fits_info.loc[sn, 'R.A.'], fits_info.loc[sn, 'Dec.']
    if verb:
        print('\n\n%s, host %s, RA %s, Dec %s' % (sn, host, ra, dec))

    sn_info = pd.DataFrame([''], columns=['objname'])

    # Finally, try searching by location; if possible, use result with similar z
    # value to OSC
    nearest_query = query_loc(ra, dec, z=ref.loc[sn, 'z'], verb=verb)
    nearest_name = nearest_query['Object Name'].replace('+', '%2B')
    sn_info = scrape_overview(nearest_name, verb=verb)
    sn_info.loc[0,'sep'] = nearest_query['Separation']
    if pd.notna(sn_info.loc[0,'ra']):
        sn_info.loc[0,'offset'] = physical_offset(ra, dec, sn_info.loc[0,'ra'], 
                sn_info.loc[0,'dec'], sn_info.loc[0,'h_dist']) # kpc

    sn_info.loc[0,'name'] = sn
    sn_info.loc[0,'host'] = host
    sn_info.loc[0,'galex_ra'] = ra
    sn_info.loc[0,'galex_dec'] = dec

    return sn_info.set_index('name')


def query_name(objname, verb=0):
    """
    Query NED based on an object name (e.g., host galaxy name)
    Inputs:
        objname (str): name of object
        verb (int or bool, optional): vebrose output? default: False
    Outputs:
        ned_table: table of query results
    """

    if verb:
        print('\tsending query for %s...' % objname)
    try:
        results = Ned.query_object(objname)
        if verb:
            print('\tcomplete')
    except:
        if verb:
            print('Object name query failed for object: %s' % objname)
        results = None
    sleep(1)
    return results


def query_loc(ra, dec, radius=1., z=None, verb=0):
    """
    Query NED based on sky coordninates; return closest match with similar z
    Inputs:
        ra, dec (float): sky coords in HHhMMmSS.Ss str format
        radius (float, optional): query radius in arcmin, default=1
        verb (int or bool, optional): verbose output? Default: False
    Outputs:
        ned_table: astropy table of query results
    """

    coord = SkyCoord(ra, dec)
    # Astroquery search by location
    if verb:
        print('\tsending query...')
    ned_results = Ned.query_region(coord, radius=radius*u.arcmin)
    if verb:
        print('\tcomplete')
    # Sort results by separation from target coords
    ned_sorted = ned_results[np.argsort(ned_results['Separation'])]
    z_sorted = ned_sorted[ned_sorted['Redshift'].mask != True]
    # Choose closest result
    ned_table = ned_sorted[0]
    # If provided a z, search for result with similar z value
    if z:
        for object in z_sorted:
            if np.abs(object['Redshift'] - z) / z < 0.1:
                ned_table = object
                break
    sleep(1)
    if verb:
        print(ned_table)
    return ned_table


def scrape_overview(objname, verb=0):
    """
    Scrape NED by object name (e.g., host galaxy name or SN name)
    Inputs:
        objname (str): name of object
        verb (int or bool, optional): vebrose output? default: False
    Outputs:
        object_info (DataFrame): info from overview table in NED
    """

    # Get BeautifulSoup from URL
    url = 'https://ned.ipac.caltech.edu/byname?objname=%s&hconst=%s&omegam=%s&omegav=%s&wmap=%s&corr_z=%s' % (objname, H_0, OMEGA_M, OMEGA_V, WMAP, CORR_Z)
    if verb:
        print('\tscraping %s ...' % url)
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')

    # mxpath labels in overview table
    main_mxpaths = dict(
        objname = 'NED_MainTable.main_col2',
        ra = 'NED_PositionDataTable.posn_col11',
        dec = 'NED_PositionDataTable.posn_col12',
        z = 'NED_BasicDataTable.basic_col4',
        z_err = 'NED_BasicDataTable.basic_col6',
        v_helio = 'NED_BasicDataTable.basic_col1',
        v_helio_err = 'NED_BasicDataTable.basic_col3',
        h_dist = 'NED_DerivedValuesTable.derived_col33',
        h_dist_err = 'NED_DerivedValuesTable.derived_col34',
        z_indep_dist = 'Redshift_IndependentDistances.ridist_col4[0]',
        type = 'NED_MainTable.main_col5',
        morph = "Classifications.class_col2[class_col1=='Galaxy Morphology']",
        a_v = 'NED_BasicDataTable.qlsize_col17',
        a_k = 'NED_BasicDataTable.qlsize_col27',
    )

    # class labels of references
    ref_classes = dict(
        posn_ref = 'ov_inside_coord_row',
        z_ref = 'ov_inside_redshift_row',
        morph_ref = 'ov_inside_classification_row',
        a_ref = 'ov_inside_prititle_row',
    )

    object_info = pd.DataFrame(columns=list(main_mxpaths.keys()))

    # Look for error messages
    err_msg = soup.find_all('div', class_='messages error')
    if len(err_msg) == 0: # if no error messages appear
        for key, mxpath in main_mxpaths.items():
            try:
                val = soup.find('span', mxpath=mxpath).get_text()
                if val == 'N/A':
                    val = np.nan
                object_info.loc[0, key] = val
            except AttributeError:
                continue
        for key, class_ in ref_classes.items():
            try:
                tr = soup.find('tr', class_=class_)
                ref = tr.find('a').get_text()
                object_info.loc[0, key] = ref
            except AttributeError:
                continue
    else:
        if verb:
            print('Object name scrape failed for object: %s' % objname)
        pass

    sleep(1)
    return object_info


def is_table(ned_table):
    """
    Returns whether the input NED table is real (at least one row) or not
    (None or 0 rows)
    """
    return (ned_table is not None and len(ned_table) > 0)


def physical_offset(ra1, dec1, ra2, dec2, h_dist):
    """
    Calculates physical offset, in kpc, between SN and host galaxy center
    Inputs:
        ra1, ra2, dec1, dec2 (str): coordinates of two objects in HHhMMmSS.Ss str format
        h_dist: Hubble distance from NED in Mpc
    """

    ra1, dec1, ra2, dec2 = Angle(ra1), Angle(dec1), Angle(ra2), Angle(dec2)
    diff = Angle(np.sqrt((ra1-ra2)**2 + (dec1-dec2)**2), u.rad)
    offset = h_dist * diff.value * 1000 # kpc
    return offset


def plot_redshifts(ned, bin_width=0.025):
    """
    Plots histogram of redshifts 
    """

    z = ned['z']
    z = z[pd.notna(z)].astype(float)
    bins = int((max(z) - min(z)) / bin_width)
    plt.hist(z, bins=bins, histtype='step')
    plt.xlabel('z')
    plt.xlim((0, max(z)))
    plt.ylabel('# of SNe')
    plt.savefig(Path('out/redshifts.png'), bbox_inches='tight', dpi=300)
    plt.xlim((0,0.5))
    plt.savefig(Path('out/redshifts_clipped.png'), bbox_inches='tight', dpi=300)
    plt.close()


def get_catalogs(ned):
    """
    Get catalog refcodes (denoted by trailing ':' in NED)
    """

    ned.dropna(subset=['z'], inplace=True)
    ref_cols = ['posn_ref', 'z_ref', 'morp_ref']
    catalogs = []
    for col in ref_cols:
        catalogs += list(ned[ned['posn_ref'].str.contains(':')]['posn_ref'])
    catalogs = list(dict.fromkeys(catalogs))
    catalog_str = '\n'.join(catalogs)
    with open(CAT_FILE, 'w') as file:
        file.write(catalog_str)
    return catalogs


def to_latex(ned, sn_info):
    """
    Outputs NED scrape output and important FITS info to LaTeX table
    """

    print('Preparing NED results...')
    # Cut SNe with z>=0.5 or unknown
    ned = ned[ned['z'] < 0.5]
    # Cut SNe with physical sep > 100 kpc
    ned = ned[ned['offset'] < 100]
    # Flag SNe with physical sep > 30 kpc
    ned.loc[ned['offset'] > 30, 'z_flag'] = 'large host offset'
    # Format coordinates, redshifts & distances
    ned['galex_coord'] = ned[['galex_ra', 'galex_dec']].agg(', '.join, axis=1)
    ned['z_str'] = ned['z'].round(6).astype('str').replace('0+$','',regex=True)
    ned['h_dist_str'] = ned['h_dist'].round(0).astype(int)
    # Sort by SN name
    ned.sort_index(inplace=True)
    # Select SN info for relevant SNe
    sn_info = sn_info[sn_info.index.isin(ned.index)]
    # Remove NED info not in selection
    ned = ned[ned.index.isin(sn_info.index)]
    # Add epoch counts and other info from sn_info
    ned['disc_date'] = sn_info['Disc. Date']
    ned['epochs_total'] = sn_info['Total Epochs']
    ned['epochs_pre'] = sn_info['Epochs Pre-SN']
    ned['epochs_post'] = sn_info['Epochs Post-SN']
    ned['delta_t_first'] = sn_info['First Epoch']
    ned['delta_t_last'] = sn_info['Last Epoch']
    ned['delta_t_next'] = sn_info['Next Epoch']
    # Add notes
    ned['notes'] = ned[['z_flag']].astype(str).replace('nan', 'N/A').agg('; '.join, axis=1)
    # Concat references
    ned['refs'] = ned[['z_ref', 'morph_ref']].astype('str').agg(';'.join, axis=1)

    # Get BibTeX entries and write bibfile
    overwrite = True
    if BIB_FILE.is_file():
        over_in = input('Previous bibliography detected. Overwrite? [y/N] ')
        overwrite = (over_in == 'y')

    if overwrite:
        print('Pulling BibTeX entries from ADS...')
        refs = list(ned['posn_ref']) + list(ned['z_ref']) + list(ned['morph_ref'])
        refs = list(dict.fromkeys(refs)) # remove duplicates
        bibcodes = {'bibcode':refs}
        with open('ads_token', 'r') as file:
            token = file.readline()
        ads_bibtex_url = 'https://api.adsabs.harvard.edu/v1/export/bibtex'
        r = requests.post(ads_bibtex_url, headers={'Authorization': 'Bearer ' + token}, data=bibcodes)
        bibtex = r.json()['export'].replace('A&A', 'AandA') # replace pesky ampersands
        with open(BIB_FILE, 'w') as file:
            file.write(bibtex)

    print('Writing to LaTeX table...')
    # Format reference bibcodes
    formatters = {'refs':table_ref}
    columns = ['name', 'disc_date', 'galex_coord', 'epochs_total', 
            'delta_t_first', 'delta_t_last', 'delta_t_next', 'z_str', 
            'h_dist_str', 'a_v', 'morph', 'refs']
    # Generate table
    ned.reset_index(inplace=True)
    latex_table = ned.to_latex(na_rep='N/A', index=False, escape=False,
        columns=columns, formatters=formatters
    )
    # Replace table header and footer with template
    # Edit this file if you need to change the number of columns or description
    with open(LATEX_TABLE_TEMPLATE, 'r') as file:
        dt_file = file.read()
        header = dt_file.split('===')[0]
        footer = dt_file.split('===')[1]
    latex_table = header + '\n'.join(latex_table.split('\n')[4:-3]) + footer
    # Write table
    with open(LATEX_TABLE_FILE, 'w') as file:
        file.write(latex_table)

    # Generate short table
    short = ned.iloc[0:20]
    short_table = short.to_latex(na_rep='N/A', index=False, escape=False,
        columns=columns, formatters=formatters
    )
    short_table = header + '\n'.join(short_table.split('\n')[4:-3]) + footer
    with open(SHORT_TABLE_FILE, 'w') as file:
        file.write(short_table)

    # Output combined CSV
    columns += ['notes', 'z_ref', 'morph_ref']
    columns -= ['refs']
    utils.output_csv(ned[columns], 'out/combined.csv', index=False)

    # Catalog bibcodes (NED has a weird format)
    get_catalogs(ned)


def table_ref(bibcodes):
    """
    Formats reference bibcodes for LaTeX table
    Input:
        bibcodes (str): list of reference codes joined with ';'
    """
    bibcodes = bibcodes.replace(';nan', '').split(';')
    bibcodes = list(dict.fromkeys(bibcodes)) # remove duplicates
    return '\citet{%s}' % ','.join([b.replace('A&A', 'AandA') for b in bibcodes])


def compress_duplicates(fits_info):
    duplicated = fits_info.groupby(['R.A.', 'Dec.'])
    fits_info['Total Epochs'] = duplicated['Total Epochs'].transform('sum')
    fits_info['Epochs Pre-SN'] = duplicated['Epochs Pre-SN'].transform('sum')
    fits_info['Epochs Post-SN'] = duplicated['Epochs Post-SN'].transform('sum')
    fits_info['First Epoch'] = duplicated['First Epoch'].transform('max')
    fits_info['Last Epoch'] = duplicated['Last Epoch'].transform('max')
    fits_info['Next Epoch'] = duplicated['Next Epoch'].transform('min')
    fits_info.drop(['Band', 'File'], axis=1, inplace=True)
    fits_info.drop_duplicates(inplace=True)
    utils.output_csv(fits_info, 'out/sninfo.csv')
    return fits_info


if __name__ == '__main__':
    main()