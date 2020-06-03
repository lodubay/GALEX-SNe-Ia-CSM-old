import pandas as pd
import numpy as np
from pathlib import Path
from astropy.time import Time
from astropy.coordinates import Angle
from astropy.io import fits
from astropy.wcs import WCS

osc = pd.read_csv('OSC-pre2014-expt-clean.csv', index_col='Name')


def galex_ab_mag(cps, band):
    const = 18.82 if band=='FUV' else 20.08
    return -2.5 * np.log10(cps) + const


def galex_flux(cps, band):
    factor = 1.4e-15 if band=='FUV' else 2.06e-16
    return factor * cps


def galex_delta_mag(cps, band, exp_time):
    factor = 0.05 if band=='FUV' else 0.027
    return -2.5 * (np.log10(cps) - np.log10(cps + np.sqrt(cps * exp_time + \
            (factor * cps * exp_time) ** 2) / exp_time))


# Get list of FITS file names from data directory
def get_fits_files(fits_dir, csv=None):
    if csv:
        fits_list = np.loadtxt(csv, delimiter=',', dtype=str)
        return [fits_dir / sn2fits(f[0], f[1]) for f in fits_list]
    else:
        return [f for f in fits_dir.glob('**/*.fits.gz')]

# Import Open Supernova Catalog csv file
def import_osc(osc_csv):
    return pd.read_csv(osc_csv, index_col='Name')


# Convert FITS file name to SN name, as listed in OSC sheet
# Required because Windows doesn't like ':' in file names
def fits2sn(fits_file, osc):
    # Pull SN name from fits file name
    sn_name = '-'.join(fits_file.name.split('-')[:-1])
    # '_' may represent either ':' or ' ' (thanks Windows)
    sn_name = sn_name.replace('_', ':')
    try:
        osc.loc[sn_name]
    except KeyError as e:
        sn_name = sn_name.replace(':', ' ')
    return sn_name


# Convert SN name to FITS file name
def sn2fits(sn, band):
    return sn.replace(':','_').replace(' ','_') + '-' + band + '.fits.gz'


class SN:
    def __init__(self, fits_file):
        '''
        name = '-'.join(fits_file.name.split('-')[:-1])
        name = name.replace('_', ':')
        try:
            osc.loc[name]
        except KeyError as e:
            name = name.replace(':', ' ')
        self.name = name
        '''
        name = fits2sn(fits_file, osc)
        self.name = name
        self.disc_date = Time(str(osc.loc[name, 'Disc. Date']), format='iso')
        self.mmax = osc.loc[name, 'mmax']
        self.host = osc.loc[name, 'Host Name']
        self.ra = Angle(osc.loc[name, 'R.A.'] + ' hours')
        self.dec = Angle(osc.loc[name, 'Dec.'] + ' deg')
        self.z = osc.loc[name, 'z']
        self.type = osc.loc[name, 'Type']


class Fits:
    def __init__(self, fits_file):
        with fits.open(fits_file) as hdu:
            self.header = hdu[0].header
            self.data = hdu[0].data
        self.sn = SN(fits_file)
        self.band = fits_file.name.split('-')[-1].split('.')[0]
        self.path = fits_file
        # exposure times (some fits images don't have individual exposure times)
        try:
            expts = [self.header['EXPT'+str(i)] for i in range(self.header['NAXIS3'])]
        except KeyError e:
            expts = []
        self.expts = np.array(expts)
        self.wcs = WCS(self.header)

