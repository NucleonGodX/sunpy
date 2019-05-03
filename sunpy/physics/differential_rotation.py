import warnings
from copy import deepcopy

import numpy as np

from astropy import units as u
from astropy.time import TimeDelta
from astropy.coordinates import SkyCoord, Longitude, BaseCoordinateFrame, get_body

from sunpy.time import parse_time
from sunpy.coordinates import Helioprojective, HeliographicStonyhurst
from sunpy.map import (all_coordinates_from_map, is_all_off_disk,
                       coordinate_is_on_disk, contains_full_disk,
                       is_all_on_disk, on_disk_bounding_coordinates,
                       map_edges)


__all__ = ['diff_rot', 'solar_rotate_coordinate', 'differential_rotate']


@u.quantity_input
def diff_rot(duration: u.s, latitude: u.deg, rot_type='howard', frame_time='sidereal'):
    """
    This function computes the change in longitude over days in degrees.

    Parameters
    -----------
    duration : `~astropy.units.Quantity`
        Number of seconds to rotate over.
    latitude : `~astropy.units.Quantity`
        heliographic coordinate latitude in Degrees.
    rot_type : `str`
        The differential rotation model to use.

        One of:

        | ``howard`` : Use values for small magnetic features from Howard et al.
        | ``snodgrass`` : Use Values from Snodgrass et. al
        | ``allen`` : Use values from Allen's Astrophysical Quantities, and simpler equation.

    frame_time : `str`
        One of : ``'sidereal'`` or  ``'synodic'``. Choose 'type of day' time reference frame.

    Returns
    -------
    longitude_delta : `~astropy.units.Quantity`
        The change in longitude over days (units=degrees)

    References
    ----------

    * `IDL code equivalent <https://hesperia.gsfc.nasa.gov/ssw/gen/idl/solar/diff_rot.pro>`__
    * `Howard rotation <http://adsabs.harvard.edu/abs/1990SoPh..130..295H>`__
    * `A review of rotation parameters (including Snodgrass values) <https://doi.org/10.1023/A:1005226402796>`__

    Examples
    --------

    Default rotation calculation over two days at 30 degrees latitude:

    >>> import numpy as np
    >>> import astropy.units as u
    >>> from sunpy.physics.differential_rotation import diff_rot
    >>> rotation = diff_rot(2 * u.day, 30 * u.deg)

    Default rotation over two days for a number of latitudes:

    >>> rotation = diff_rot(2 * u.day, np.linspace(-70, 70, 20) * u.deg)

    With rotation type 'allen':

    >>> rotation = diff_rot(2 * u.day, np.linspace(-70, 70, 20) * u.deg, 'allen')
    """

    latitude = latitude.to(u.deg)

    sin2l = (np.sin(latitude))**2
    sin4l = sin2l**2

    rot_params = {'howard': [2.894, -0.428, -0.370] * u.urad / u.second,
                  'snodgrass': [2.851, -0.343, -0.474] * u.urad / u.second,
                  'allen': [14.44, -3.0, 0] * u.deg / u.day
                  }

    if rot_type not in ['howard', 'allen', 'snodgrass']:
        raise ValueError(("rot_type must equal one of "
                          "{{ {} }}".format(" | ".join(rot_params.keys()))))

    A, B, C = rot_params[rot_type]

    # This calculation of the rotation assumes a sidereal frame time.
    rotation = (A + B * sin2l + C * sin4l) * duration

    # Applying this correction assumes that the observer is on the Earth,
    # and that the Earth is at the same distance from the Sun at all times
    # during the year.
    if frame_time == 'synodic':
        rotation -= 0.9856 * u.deg / u.day * duration

    return Longitude(rotation.to(u.deg))


def _get_new_observer(initial_obstime, observer, time):
    """
    Helper function that interprets the possible ways of specifying the
    input to the solar coordinate rotation function.

    If the "observer" argument is not `None`, it is used to specify the location
    of the new observer in space and time.

    If the "time" argument is not `None`, it is used to calculate the duration
    over which to the amount of solar rotation is calculated. Note that using
    the "time" keyword assumes that the new observer is on the Earth. This may
    be a reasonable assumption depending on the application.

    Either the "observer" or "time" argument must be specified, but both
    cannot be specified at the same time and both cannot be None.

    Parameters
    ----------
    initial_obstime : `~astropy.time.Time`
        The initial time before solar rotation has been applied.

    observer : `~astropy.coordinates.BaseCoordinateFrame`, `~astropy.coordinates.SkyCoord`, None
        The location of the new observer in space and time (the observer must have an
        interpretable obstime property).

    time : `~astropy.time.Time`, `~astropy.time.TimeDelta`, `~astropy.units.Quantity`, None
        Used to define the duration over which the amount of solar rotation is
        calculated.  If 'time' is an `~astropy.time.Time` then the time interval is
        "time - initial_obstime"; if 'time' is `~astropy.time.TimeDelta` or
        `~astropy.units.Quantity` then the calculation is "initial_obstime + time".

    Returns
    -------
    new_observer : `~astropy.coordinates.SkyCoord`, `~astropy.coordinates.BaseCoordinateFrame`
        The position of the observer in space and time. If the "time" keyword is used
        the output is an `~astropy.coordinates.SkyCoord`. If the "observer" keyword
        is not None the output has the same type as the "observer" keyword.  In all cases
        the output is specified in the heliographic Stonyhurst coordinate system.
    """
    # Check the input and create the new observer
    if (observer is not None) and (time is not None):
        raise ValueError("Either the 'observer' or the 'time' keyword must be specified, but not both simultaneously.")
    elif observer is not None:
        # Check that the new_observer is specified correctly.
        if not (isinstance(observer, (BaseCoordinateFrame, SkyCoord))):
            raise ValueError(
                "The 'observer' must be an astropy.coordinates.BaseCoordinateFrame or an astropy.coordinates.SkyCoord.")
        if observer.obstime is None:
            raise ValueError("The observer 'obstime' property must not be None.")
        new_observer = observer
    elif time is not None:
        warnings.warn("Using 'time' assumes an Earth-based observer.")
        if isinstance(time, TimeDelta) or isinstance(time, u.Quantity):
            new_observer_time = initial_obstime + time
        else:
            new_observer_time = parse_time(time)

        new_observer = get_body("earth", new_observer_time)
    else:
        raise ValueError("Either the 'observer' or the 'time' keyword must not be None.")

    return new_observer.transform_to(HeliographicStonyhurst)


def solar_rotate_coordinate(coordinate, observer=None, time=None, **diff_rot_kwargs):
    """
    Given a coordinate on the Sun, calculate where that coordinate maps to
    as seen by a new observer at some later or earlier time, given that
    the input coordinate rotates according to the solar rotation profile.

    The amount of solar rotation is based on the amount of time between the
    observation time of the input coordinate and the observation time of the
    new observer. The new observer is specified in one of two ways, either
    using the "observer" or "time" keywords.

    If the "observer" keyword is set, it is used to specify the location
    of the new observer in space and time.  The difference between the
    coordinate time and the new observer time is used to calculate the amount
    of solar rotation applied, and the location of the new observer in space
    is used to calculate where the rotated coordinate is as seen from the
    new observer.

    If the "time" keyword is set, it is used to specify the number of
    seconds to rotate the coordinate by. Note that using the "time" keyword
    assumes that the new observer is on the Earth. This may be a reasonable
    assumption depending on the application.

    Either the "observer" or "time" keyword must be specified, but both
    cannot be specified at the same time.

    Parameters
    ----------
    coordinate : `~astropy.coordinates.SkyCoord`
        Any valid coordinate which is transformable to Heliographic Stonyhurst.

    observer : `~astropy.coordinates.BaseCoordinateFrame`, `~astropy.coordinates.SkyCoord`, None
        The location of the new observer in space and time (the observer must have an
        interpretable obstime property).

    time : `~astropy.time.Time`, `~astropy.time.TimeDelta`, `~astropy.units.Quantity`, None

    diff_rot_kwargs : `dict`
        Keyword arguments are passed on as keyword arguments to `~sunpy.physics.differential_rotation.diff_rot`.
        Note that the keyword "frame_time" is automatically set to the value
        "sidereal".

    Returns
    -------
    coordinate : `~astropy.coordinates.SkyCoord`
        The locations of the input coordinates after the application of
        solar rotation as seen from the point-of-view of the new observer.

    Example
    -------
    >>> import astropy.units as u
    >>> from astropy.coordinates import SkyCoord, get_body
    >>> from sunpy.coordinates import Helioprojective
    >>> from sunpy.physics.differential_rotation import solar_rotate_coordinate
    >>> from sunpy.time import parse_time
    >>> start_time = parse_time('2010-09-10 12:34:56')
    >>> end_time = parse_time('2010-09-10 13:34:56')
    >>> c = SkyCoord(-570*u.arcsec, 120*u.arcsec, obstime=start_time, frame=Helioprojective)
    >>> solar_rotate_coordinate(c, time=end_time)
    <SkyCoord (Helioprojective: obstime=2010-09-10T13:34:56.000, rsun=695700.0 km, observer=<HeliographicStonyhurst Coordinate for 'earth'>): (Tx, Ty, distance) in (arcsec, arcsec, km)
    (-562.89557218, 119.31528517, 1.50084836e+08)>
    >>> new_observer = get_body("earth", end_time)
    >>> solar_rotate_coordinate(c, observer=new_observer)
    <SkyCoord (Helioprojective: obstime=2010-09-10T13:34:56.000, rsun=695700.0 km, observer=<HeliographicStonyhurst Coordinate for 'earth'>): (Tx, Ty, distance) in (arcsec, arcsec, km)
        (-562.89557218, 119.31528517, 1.50084836e+08)>
    """
    # Check the input and create the new observer
    new_observer = _get_new_observer(coordinate.obstime, observer, time)

    # The keyword "frame_time" must be explicitly set to "sidereal"
    # when using this function.
    diff_rot_kwargs.update({"frame_time": "sidereal"})

    # Calculate the interval between the start and end time
    interval = (new_observer.obstime - coordinate.obstime).to(u.s)

    # Compute Stonyhurst Heliographic co-ordinates - returns (longitude,
    # latitude). Points off the limb are returned as nan.
    heliographic_coordinate = coordinate.transform_to(HeliographicStonyhurst)

    # Compute the differential rotation
    drot = diff_rot(interval, heliographic_coordinate.lat.to(u.degree), **diff_rot_kwargs)

    # Rotate the input co-ordinate as seen by the original observer
    heliographic_rotated = SkyCoord(heliographic_coordinate.lon + drot, heliographic_coordinate.lat,
                                    obstime=coordinate.obstime, observer=coordinate.observer,
                                    frame=HeliographicStonyhurst)

    # Calculate where the rotated co-ordinate appears as seen by new observer,
    # and then transform it into the co-ordinate system of the input
    # co-ordinate.
    return heliographic_rotated.transform_to(new_observer).transform_to(coordinate.frame.name)


def _rotate_submap_edge(smap, pixels, observer, **diff_rot_kwargs):
    """
    Helper function that is used to calculate where the edge of a rectangular
    map move to on rotation.  If all the pixels passed in are not on disk and
    therefore subject to solar differential rotation, the coordinates
    corresponding to the input pixels are returned.

    Parameters
    ----------
    smap : `~sunpy.map.Map`
        The input map from which the pixel coordinates are calculated.

    pixels : `~astropy.units.Quantity`
        A Quantity array of shape (M, 2) in pixel units.  Values (:, 0) are the y values of the
        pixel indices, and values (:, 1) are the x values of the pixel indices.

    observer : `~astropy.coordinates.SkyCoord`
        The location of the observer.

    diff_rot_kwargs : None, `~dict`
        Keyword arguments accepted by `~sunpy.physics.differential_rotation.diff_rot`.

    Returns
    -------
    coordinates : `~astropy.coordinates.SkyCoord`
        The coordinates of a rotated edge.
    """
    # Coordinates
    c = smap.pixel_to_world(pixels[:, 1], pixels[:, 0])

    # Only apply solar rotation if all coordinates are on the disk.
    if np.all(~coordinate_is_on_disk(c, smap.rsun_obs)):
        coordinates = deepcopy(c)
    else:
        coordinates = solar_rotate_coordinate(c, observer=observer, **diff_rot_kwargs)
    return coordinates


def _get_extreme_position(coords, axis, operator=np.nanmax):
    """
    Helper function that calculates an extreme position from a list of
    coordinates.

    Parameters
    ----------
    coords : `~list`
        Each member of the list is a `~astropy.coordinates.SkyCoord`.

    axis :  'Tx', 'Ty'
        Which helioprojective axis to examine.

    operator : numpy function
        A numpy function that finds an extreme value in an array
        of helioprojective coordinate values.

    Returns
    -------
    extreme value : `~astropy.units.Quantity`
        An extreme position in units of arcseconds.
    """

    extreme_values = []
    for coord in coords:
        if axis == 'Tx':
            extreme_value = operator(coord.Tx.value)
        elif axis == 'Ty':
            extreme_value = operator(coord.Ty.value)
        else:
            raise ValueError('The "axis" argument must be either "Tx" or "Ty".')
        extreme_values.append(extreme_value)

    return operator(extreme_values)


def _get_bounding_coordinates(coords):
    """
    Helper function that returns the bottom left and top right coordinates
    that define a bounding box enclosing the passed in coordinates.

    Parameters
    ----------
    coords : `~list`
        Each member of the list is a `~astropy.coordinates.SkyCoord`.

    Returns
    -------
    bottom_left, top_right : `~astropy.coordinates.SkyCoord`
        A  `~astropy.coordinates.SkyCoord` of length 2 that specifies the
        bottom left hand (first entry) and top right hand (second entry) corner
        of a bounding box that minimally encloses all the input coordinates.
    """
    rotated_x_min = _get_extreme_position(coords, "Tx", operator=np.nanmin)
    rotated_x_max = _get_extreme_position(coords, "Tx", operator=np.nanmax)
    rotated_y_min = _get_extreme_position(coords, "Ty", operator=np.nanmin)
    rotated_y_max = _get_extreme_position(coords, "Ty", operator=np.nanmax)
    return SkyCoord([rotated_x_min, rotated_x_max] * u.arcsec,
                    [rotated_y_min, rotated_y_max] * u.arcsec,
                    frame=Helioprojective, observer=coords[0].observer)


def _warp_sun_coordinates(xy, smap, new_observer, **diff_rot_kwargs):
    """
    Helper function that returns a new list of coordinates for each input coord.
    This is an inverse function needed by the scikit-image `transform.warp`
    function.

    Parameters
    ----------
    xy : `numpy.ndarray`
        Array from `transform.warp`.

    smap : `~sunpy.map.GenericMap`
        Original map that we want to transform.

    Returns
    -------
    xy2 : `~numpy.ndarray`
        Array with the inverse transformation.
    """
    # We start by converting the pixel to world
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')

        # The time interval between the new observer time and the map observation time.
        interval = (parse_time(new_observer.obstime) - parse_time(smap.date)).to(u.s)

        # These are the co-ordinates at the new observer.
        heliographic_coordinate = all_coordinates_from_map(smap).transform_to(new_observer).transform_to(HeliographicStonyhurst)

        # Compute the differential rotation.
        drot = diff_rot(interval, heliographic_coordinate.lat.to(u.degree), **diff_rot_kwargs)

        # Subtract the differential rotation.  This is the inverse of adding in
        # differential rotation.
        rotated_coord = SkyCoord(heliographic_coordinate.lon - drot, heliographic_coordinate.lat,
                                 obstime=new_observer.obstime, observer=new_observer,
                                 frame=HeliographicStonyhurst).transform_to(smap.observer_coordinate)

        # Find which coordinates are not on the visible disk of the Sun.
        with np.errstate(invalid='ignore'):
            occult = np.logical_or(np.less(rotated_coord.lon, -90 * u.deg),
                                   np.greater(rotated_coord.lon, 90 * u.deg))

        # NaN-ing values that move to the other side of the sun
        rotated_coord.data.lon[occult] = np.nan * u.deg
        rotated_coord.data.lat[occult] = np.nan * u.deg
        rotated_coord.cache.clear()

        # Go back to pixel co-ordinates
        x2, y2 = smap.world_to_pixel(rotated_coord)

    # Re-stack the data to make it correct output form
    xy2 = np.dstack([x2.T.value.flat, y2.T.value.flat])[0]

    # Returned a masked array with the non-finite entries masked.
    return np.ma.array(xy2, mask=np.isnan(xy2))


def differential_rotate(smap, observer=None, time=None, **diff_rot_kwargs):
    """
    Function to apply solar differential rotation to a sunpy map.

    Parameters
    ----------
    smap : `~sunpy.map.GenericMap`
        Original map that we want to transform.

    observer : `~astropy.coordinates.BaseCoordinateFrame`, `~astropy.coordinates.SkyCoord`
        The location of the new observer.
        Instruments in Earth orbit can be approximated by using the position
        of the Earth at the observation time of the new observer.

    time : sunpy-compatible time
        date/time at which the input co-ordinate will be rotated to.

    Returns
    -------
    differential_rotate : `~sunpy.map.GenericMap`
        A map with the result of applying solar differential rotation to the
        input map.
    """
    # If the entire map is off-disk, return an error so the user is aware.
    if is_all_off_disk(smap):
        raise ValueError("The entire map is off disk. No data to differentially rotate.")

    # Get the new observer
    new_observer = _get_new_observer(smap.date, observer, time)

    # Only this function needs scikit image
    from skimage import transform
    from sunpy.image.util import to_norm, un_norm
    # Import map here for performance reasons.
    import sunpy.map

    # Check whether the input contains the full disk of the Sun
    is_sub_full_disk = not contains_full_disk(smap)
    if is_sub_full_disk:
        # Find the minimal submap of the input map that includes all the
        # on disk pixels. This is required in order to calculate how
        # much to pad the output (solar-differentially rotated) data array by
        # compared to the input map.
        # The amount of padding is dependent on the amount of solar differential
        # rotation and where the on-disk pixels are (since these pixels are the only ones
        # subject to solar differential rotation).
        if not is_all_on_disk(smap):
            # Get the bottom left and top right coordinates that are the
            # vertices that define a box that encloses the on disk pixels
            bottom_left, top_right = on_disk_bounding_coordinates(smap)

            # Create a submap that excludes the off disk emission that does
            # not need to be rotated.
            smap = smap.submap(bottom_left, top_right)
        bottom_left = smap.bottom_left_coord
        top_right = smap.top_right_coord

        # Get the edges of the minimal submap that contains all the on-disk pixels.
        edges = map_edges(smap)

        # Calculate where the output array moves to.
        # Rotate the top and bottom edges
        rotated_top = _rotate_submap_edge(smap, edges["top"], observer=new_observer, **diff_rot_kwargs)
        rotated_bottom = _rotate_submap_edge(smap, edges["bottom"], observer=new_observer, **diff_rot_kwargs)

        # Rotate the left and right hand edges
        rotated_lhs = _rotate_submap_edge(smap, edges["lhs"], observer=new_observer, **diff_rot_kwargs)
        rotated_rhs = _rotate_submap_edge(smap, edges["rhs"], observer=new_observer, **diff_rot_kwargs)

        # Calculate the bounding box of the rotated map
        rotated_bl, rotated_tr = _get_bounding_coordinates([rotated_top, rotated_bottom, rotated_lhs, rotated_rhs])

        # Calculate the maximum distance in pixels the map has moved by comparing
        # how far the original and rotated bounding boxes have moved.
        diff_x = [(np.abs(rotated_bl.Tx - bottom_left.Tx)).value, (np.abs(rotated_tr.Tx - top_right.Tx)).value]
        deltax = int(np.ceil(np.max(diff_x) / smap.scale.axis1).value)

        diff_y = [(np.abs(rotated_bl.Ty - bottom_left.Ty)).value, (np.abs(rotated_tr.Ty - top_right.Ty)).value]
        deltay = int(np.ceil(np.max(diff_y) / smap.scale.axis2).value)

        # Create a new `smap` with the padding around it
        padded_data = np.pad(smap.data, ((deltay, deltay), (deltax, deltax)), 'constant', constant_values=0)
        padded_meta = deepcopy(smap.meta)
        padded_meta['naxis2'], padded_meta['naxis1'] = smap.data.shape

        padded_meta['crpix1'] += deltax
        padded_meta['crpix2'] += deltay

        # Create the padded map that will be used to create the rotated map.
        smap = sunpy.map.Map(padded_data, padded_meta)

    # Check for masked maps
    if smap.mask is not None:
        smap_data = np.ma.array(smap.data, mask=smap.mask)
    else:
        smap_data = smap.data

    # Create the arguments for the warp function.
    warp_args = {'smap': smap, 'new_observer': new_observer}
    warp_args.update(diff_rot_kwargs)

    # Apply solar differential rotation as a scikit-image warp
    out_data = transform.warp(to_norm(smap_data), inverse_map=_warp_sun_coordinates, map_args=warp_args)

    # Recover the original intensity range.
    out_data = un_norm(out_data, smap.data)

    # Update the meta information with the new date and time.
    out_meta = deepcopy(smap.meta)
    if out_meta.get('date_obs', False):
        del out_meta['date_obs']
    out_meta['date-obs'] = new_observer.obstime.strftime("%Y-%m-%dT%H:%M:%S.%f")

    # Need to update the observer location for the output map.
    out_meta['hglt_obs'] = new_observer.lat.value
    out_meta['hgln_obs'] = new_observer.lon.value
    out_meta['dsun_obs'] = new_observer.radius.to(u.m).value

    if is_sub_full_disk:
        # Define a new reference pixel and the value at the reference pixel.
        # Note that according to the FITS convention the first pixel in the
        # image is at (1.0, 1.0).
        center_rotated = solar_rotate_coordinate(smap.center, observer=new_observer, **diff_rot_kwargs)
        out_meta['crval1'] = center_rotated.Tx.value
        out_meta['crval2'] = center_rotated.Ty.value
        out_meta['crpix1'] = 1 + smap.data.shape[1]/2.0 + ((center_rotated.Tx - smap.center.Tx)/smap.scale.axis1).value
        out_meta['crpix2'] = 1 + smap.data.shape[0]/2.0 + ((center_rotated.Ty - smap.center.Ty)/smap.scale.axis2).value
        return sunpy.map.Map(out_data, out_meta).submap(rotated_bl, rotated_tr)
    else:
        return sunpy.map.Map(out_data, out_meta)
