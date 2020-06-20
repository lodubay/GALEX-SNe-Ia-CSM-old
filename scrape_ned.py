import numpy as np
import pandas as pd
import requests
import urllib.request
import time
from bs4 import BeautifulSoup
import re
from selenium import webdriver
from selenium.webdriver import ActionChains
from requests_html import HTMLSession
import pyppdf.patch_pyppeteer
from tqdm import tqdm
from astropy.coordinates import SkyCoord
from astroquery.ned import Ned
from astropy import units as u
from pathlib import Path

H_0 = 67.8 # km/sec/Mpc
OMEGA_M = 0.308
OMEGA_V = 0.692
QUERY_RADIUS = 1. # arcmin
NED_RESULTS_FILE = Path('out/scraped_table.csv')
NED_RESULTS_FILE_TMP = Path('out/scraped_table-tmp.csv')


def main():

    fits_info = pd.read_csv('out/fitsinfo.csv', index_col='Name')
    sample = pd.Series(fits_info.index.drop_duplicates())
    ref = pd.read_csv('ref/OSC-pre2014-v2-clean.csv', index_col='Name')

    gen_tab = True
    if NED_RESULTS_FILE.is_file():
        i = input('Previous NED query results found. Overwrite? [y/N] ')
        gen_tab = True if i == 'y' else False

    if gen_tab:
        # Scrape NED for all SNe in sample
        scraped = pd.concat([parse_html(sn, fits_info, ref) for sn in tqdm(sample)],
                ignore_index=True)
        scraped.set_index('name')

        try:
            scraped.to_csv(NED_RESULTS_FILE, index=False)
        except PermissionError:
            scraped.to_csv(NED_RESULTS_FILE_TMP, index=False)
    else:
        ned = pd.read_csv(NED_RESULTS_FILE, index_col='name')
    

    '''
    options = webdriver.FirefoxOptions()
    options.add_argument('--ignore-certificate-errors')
    options.add_argument('--incognito')
    options.add_argument('--headless')
    driver = webdriver.Firefox(executable_path='./geckodriver.exe', options=options)
    driver.get(url)
    action = ActionChains(driver)
    redshifts_table = driver.find_elements_by_xpath('/html/body/div[1]/div[2]/section/form/div/div/div[2]/div/div[4]/fieldset[2]/ov_legend/span/div/span')[0]
    redshifts_button = driver.find_element_by_xpath('/html/body/div[1]/div[2]/section/form/div/div/div[2]/div/div[4]/fieldset[2]/ov_legend/span/div/div[1]/div')
    print(redshifts_button.text)
    #driver.execute_script('arguments[0].click();', redshifts_table)
    action.move_to_element(redshifts_button)
    action.pause(1)
    action.click(redshifts_button)
    action.perform()
    text_view = driver.find_elements_by_xpath('/html/body/div[1]/div[2]/section/form/div/div/div[2]/div/div[4]/fieldset[2]/ov_legend/span/div/div[2]/table/tbody/tr/td/div/div/div/div/div[1]/div[3]/div[2]')[0]
    print(text_view)
    time.sleep(0.1)
    page_source = driver.page_source
    soup = BeautifulSoup(page_source, 'lxml')

    z = driver.find_elements_by_xpath('/html/body/div[1]/div[2]/section/form/div/div/div[2]/div/div[4]/fieldset[2]/ov_legend/span/div/div[2]/table/tbody/tr/td/div/div/div/div/div[2]/div/div[2]/div[1]/div[3]/div[2]/div/div[1]/div[2]/div/div[1]/div')
    print(z)
    z_tab_href = soup.find('a', text=re.compile('Redshifts \([0-9]+\)'))['href']

    session = HTMLSession()
    resp = session.get(url)
    resp.html.render()

    #soup = BeautifulSoup(resp.html.html, 'lxml')

    # Redshift values from Redshifts tab
    print(redshifts[0].text)
    z_tab_href = soup.find('a', text=re.compile('Redshifts \([0-9]+\)'))['href']
    driver.get(url+z_tab_href)
    collapsible_tables = driver.find_elements_by_class_name('panel_collapsible_title')
    for table in collapsible_tables:
        driver.execute_script('arguments[0].click();', table)
        time.sleep(0.1)
    redshifts_tab_source = driver.page_source
    redshifts_soup = BeautifulSoup(redshifts_tab_source, 'lxml')
    z_tab = redshifts_soup.find('div', id=z_tab_href[1:])
    measured_z_table = z_tab.find('div', {'class': 'panel_collapsible_title'})

    #z_tab = soup.find('div', id=z_tab_href[1:])
    #preferred_z = z_tab.find('span', mxpath='NED_BasicDataTable.basic_col4').get_text()
    #measured_z_table = z_tab.find('div', {'class': 'panel_collapsible_title'})
    #script = z_tab.find('script', {'type': 'text/javascript'})
    #print(measured_z_table)

    # Redshift-independent distances from Distances tab
    dist_tab_href = soup.find('a', text=re.compile('Distances \([0-9]+\)'))['href']
    dist_tab = soup.find('div', id=dist_tab_href[1:])
    '''


def parse_html(sn, fits_info, ref):

    host = ref.loc[sn, 'Host Name']
    ra, dec = fits_info.loc[sn, 'R.A.'], fits_info.loc[sn, 'Dec.']

    # First, try searching by SN name
    soup = get_soup(sn)
    df = scrape_overview(soup)

    # Next, try searching by host name
    if len(df) == 0 or df.loc[0,'z'] == 'N/A':
        soup = get_soup(host)
        df = scrape_overview(soup)

    # Finally, try searching by location
    if len(df) == 0 or df.loc[0,'z'] == 'N/A':
        nearest, sep = query_loc(ra, dec, objname=sn)
        #print(nearest)
        soup = get_soup(nearest)
        df = scrape_overview(soup)
        df.loc[0,'sep'] = sep

    df.loc[0,'name'] = sn
    df.loc[0,'host'] = host

    return df


def get_soup(objname):

    url = 'https://ned.ipac.caltech.edu/byname?objname=%s&hconst=%s&omegam=%s&\
           omegav=%s#tab_3' % (objname, H_0, OMEGA_M, OMEGA_V)
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')
    return soup


def query_loc(ra, dec, radius=1., objname=''):

    coord = SkyCoord(ra, dec)
    # Astroquery search by location
    ned_results = Ned.query_region(coord, radius=radius*u.arcmin)
    # Sort results by separation from target coords
    ned_sorted = ned_results[np.argsort(ned_results['Separation'])]
    # Choose closest result
    ned_table = ned_sorted[0:1]
    # If location search turns up the original object, check again
    if ned_table['Object Name'][0] == objname and len(ned_sorted) > 1:
        ned_table = ned_sorted[1:2]
    return ned_table['Object Name'][0], ned_table['Separation'][0]


def scrape_overview(soup):

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

    ref_classes = dict(
        posn_ref = 'ov_inside_coord_row',
        z_ref = 'ov_inside_redshift_row',
        morph_ref = 'ov_inside_classification_row',
        a_ref = 'ov_inside_prititle_row',
    )

    df = pd.DataFrame(columns=list(main_mxpaths.keys()))

    try:
        for key, mxpath in main_mxpaths.items():
            val = soup.find('span', mxpath=mxpath).get_text()
            df.loc[0, key] = val
    except AttributeError:
        pass

    for key, class_ in ref_classes.items():
        tr = soup.find('tr', class_=class_)
        if tr:
            a = tr.find('a')
            if a:
                ref = a.get_text()
                df.loc[0, key] = ref

    return df


if __name__ == '__main__':
    main()