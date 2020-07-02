import pandas as pd
import numpy as np

from astropy.coordinates import SkyCoord
import astropy.table as tbl
from astropy.stats import sigma_clipped_stats

from photutils import DAOStarFinder

import matplotlib.pyplot as plt
import matplotlib as mpl

from pathlib import Path
from tqdm import tqdm

import phot
import utils


def find_stars(data, threshold=10., fwhm=3.):
    mean, median, std = sigma_clipped_stats(data, sigma=3.0)
    if std == 0.:
        std = np.std(data)
    daofind = DAOStarFinder(threshold = threshold * std, fwhm=fwhm)
    sources = daofind(data - median)
    return sources


'''
Runs DAOPhot star finder on a given FITS image, calculates GALEX magnitudes and 
sky coordinates, and returns an astropy Table.

fits_obj: Fits object
epoch: index of specific image
'''
def get_stars(fits_obj, epoch):
    # DAOPhot star locations
    img = fits_obj.data[epoch]
    stars = find_stars(img, threshold=5)

    # GALEX magnitude conversion
    try:
        stars['ab_mag'] = utils.galex_ab_mag(stars['flux'], fits_obj.band)
    except TypeError:
            print(stars)
    stars['delta_mag'] = utils.galex_delta_mag(stars['flux'], fits_obj.band, fits_obj.expts[epoch])

    # Convert pixels to sky coordinates
    sky_positions = [SkyCoord.from_pixel(s['xcentroid'], s['ycentroid'], \
            fits_obj.wcs) for s in stars]
    sky_positions = SkyCoord.from_pixel(stars['xcentroid'], stars['ycentroid'], fits_obj.wcs)
    stars['ra'] = sky_positions.ra
    stars['dec'] = sky_positions.dec

    # Epoch information
    stars['tmean'] = [fits_obj.tmeans[epoch]] * len(stars)
    stars['epoch'] = [epoch] * len(stars)

    return stars


def plot_sys_error(fits_file):
    f = utils.Fits(fits_file)
    if f.header['NAXIS'] == 2:
        f.data = np.array([f.data])

    fields = []

    for i, img in enumerate(tqdm(f.data)):
        fields.append(get_stars(f, i))

    # Plot
    stars = tbl.vstack(fields)

    fig, axes = plt.subplots(2)
    ax = axes[0]
    ax.scatter(x=stars['ab_mag'], y=stars['delta_mag'], s=0.5, c=stars['epoch'], 
            cmap=plt.get_cmap('Greys'))
    ax.set_xlabel('m_AB')
    ax.set_ylabel('delta m_AB')
    ax.set_title(f.sn.name + ' ' + f.band)

    ax = axes[1]
    ax.scatter(x=stars['epoch'], y=stars['ab_mag'], s=stars['delta_mag']*10)
    ax.set_xlabel('epoch')
    ax.set_ylabel('mag')
    plt.show()


if __name__ == '__main__':
    single_img_fits = '/mnt/d/GALEX_SNeIa_REU/fits/ASASSN-13ch-FUV.fits.gz'
    two_img_fits = 'sample/ASASSN-13cp-NUV.fits.gz'
    many_img_fits = ['/mnt/d/GALEX_SNeIa_REU/fits/PTF12hdb-NUV.fits.gz',
            'sample/SN2006lo-NUV.fits.gz']
    plot_sys_error(Path(many_img_fits[1]))