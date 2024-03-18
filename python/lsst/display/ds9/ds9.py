# This file is part of display_ds9.
#
# Developed for the LSST Data Management System.
# This product includes software developed by the LSST Project
# (https://www.lsst.org).
# See the COPYRIGHT file at the top-level directory of this distribution
# for details of code ownership.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

__all__ = ["Ds9Error", "getXpaAccessPoint", "ds9Version", "Buffer",
           "selectFrame", "ds9Cmd", "initDS9", "Ds9Event", "DisplayImpl"]

import os
import re
import shutil
import sys
import time

import numpy as np

import lsst.afw.display.interface as interface
import lsst.afw.display.virtualDevice as virtualDevice
import lsst.afw.display.ds9Regions as ds9Regions

try:
    from . import xpa as xpa
except ImportError as e:
    print("Cannot import xpa: %s" % (e), file=sys.stderr)

import lsst.afw.display as afwDisplay
import lsst.afw.math as afwMath

try:
    needShow
except NameError:
    needShow = True  # Used to avoid a bug in ds9 5.4


class Ds9Error(IOError):
    """Represents an error communicating with DS9.
    """


try:
    _maskTransparency
except NameError:
    _maskTransparency = None


def getXpaAccessPoint():
    """Parse XPA_PORT if set and return an identifier to send DS9 commands.

    Returns
    -------

    xpaAccessPoint : `str`
        Either a reference to the local host with the configured port, or the
        string ``"ds9"``.

    Notes
    -----
    If you don't have XPA_PORT set, the usual xpans tricks will be played
    when we return ``"ds9"``.
    """
    xpa_port = os.environ.get("XPA_PORT")
    if xpa_port:
        mat = re.search(r"^DS9:ds9\s+(\d+)\s+(\d+)", xpa_port)
        if mat:
            port1, port2 = mat.groups()

            return "127.0.0.1:%s" % (port1)
        else:
            print("Failed to parse XPA_PORT=%s" % xpa_port, file=sys.stderr)

    return "ds9"


def ds9Version():
    """Get the version of DS9 in use.

    Returns
    -------
    version : `str`
        Version of DS9 in use.
    """
    try:
        v = ds9Cmd("about", get=True)
        return v.splitlines()[1].split()[1]
    except Exception as e:
        print("Error reading version: %s" % e, file=sys.stderr)
        return "0.0.0"


try:
    cmdBuffer
except NameError:
    # internal buffersize in xpa. Sigh; esp. as the 100 is some needed slop
    XPA_SZ_LINE = 4096 - 100

    class Buffer(object):
        """Buffer to control sending commands to DS9.

        Notes
        -----
        The usual usage pattern is:

        >>> with ds9.Buffering():
        ...     # bunches of ds9.{dot,line} commands
        ...     ds9.flush()
        ...     # bunches more ds9.{dot,line} commands
        """

        def __init__(self, size=0):
            self._commands = ""         # list of pending commands
            self._lenCommands = len(self._commands)
            self._bufsize = []          # stack of bufsizes

            self._bufsize.append(size)  # don't call self.size() as ds9Cmd isn't defined yet

        def set(self, size, silent=True):
            """Set the ds9 buffer size to size.

            Parameters
            ----------
            size : `int`
                Size of buffer. Requesting a negative size provides the
                largest possible buffer given bugs in xpa.
            silent : `bool`, optional
                Do not print error messages (default `True`).
            """
            if size < 0:
                size = XPA_SZ_LINE - 5

            if size > XPA_SZ_LINE:
                print("xpa silently hardcodes a limit of %d for buffer sizes (you asked for %d) " %
                      (XPA_SZ_LINE, size), file=sys.stderr)
                self.set(-1)            # use max buffersize
                return

            if self._bufsize:
                self._bufsize[-1] = size  # change current value
            else:
                self._bufsize.append(size)  # there is no current value; set one

            self.flush(silent=silent)

        def _getSize(self):
            """Get the current DS9 buffer size.

            Returns
            -------
            size : `int`
                Size of buffer.
            """
            return self._bufsize[-1]

        def pushSize(self, size=-1):
            """Replace current DS9 command buffer size.

            Parameters
            ----------
            size : `int`, optional
                Size of buffer. A negative value sets the largest possible
                buffer.

            Notes
            -----
            See also `popSize`.
            """
            self.flush(silent=True)
            self._bufsize.append(0)
            self.set(size, silent=True)

        def popSize(self):
            """Switch back to the previous command buffer size.

            Notes
            -----
            See also `pushSize`.
            """
            self.flush(silent=True)

            if len(self._bufsize) > 1:
                self._bufsize.pop()

        def flush(self, silent=True):
            """Flush the pending commands.

            Parameters
            ----------
            silent : `bool`, optional
                Do not print error messages.
            """
            ds9Cmd(flush=True, silent=silent)

    cmdBuffer = Buffer(0)


def selectFrame(frame):
    """Convert integer frame number to DS9 command syntax.

    Parameters
    ----------
    frame : `int`
        Frame number

    Returns
    -------
    frameString : `str`
    """
    return "frame %d" % (frame)


def ds9Cmd(cmd=None, trap=True, flush=False, silent=True, frame=None, get=False):
    """Issue a DS9 command, raising errors as appropriate.

    Parameters
    ----------
    cmd : `str`, optional
        Command to execute.
    trap : `bool`, optional
        Trap errors.
    flush : `bool`, optional
        Flush the output.
    silent : `bool`, optional
        Do not print trapped error messages.
    frame : `int`, optional
        Frame number on which to execute command.
    get : `bool`, optional
        Return xpa response.
    """

    global cmdBuffer
    if cmd:
        if frame is not None:
            cmd = "%s;" % selectFrame(frame) + cmd

        if get:
            return xpa.get(None, getXpaAccessPoint(), cmd, "").strip()

        # Work around xpa's habit of silently truncating long lines; the value
        # ``5`` provides some margin to handle new lines and the like.
        if cmdBuffer._lenCommands + len(cmd) > XPA_SZ_LINE - 5:
            ds9Cmd(flush=True, silent=silent)

        cmdBuffer._commands += ";" + cmd
        cmdBuffer._lenCommands += 1 + len(cmd)

    if flush or cmdBuffer._lenCommands >= cmdBuffer._getSize():
        cmd = (cmdBuffer._commands + "\n")
        cmdBuffer._commands = ""
        cmdBuffer._lenCommands = 0
    else:
        return

    cmd = cmd.rstrip()
    if not cmd:
        return

    try:
        ret = xpa.set(None, getXpaAccessPoint(), cmd, "", "", 0)
        if ret:
            raise IOError(ret)
    except IOError as e:
        if not trap:
            raise Ds9Error("XPA: %s, (%s)" % (e, cmd))
        elif not silent:
            print("Caught ds9 exception processing command \"%s\": %s" % (cmd, e), file=sys.stderr)


def initDS9(execDs9=True):
    """Initialize DS9.

    Parameters
    ----------
    execDs9 : `bool`, optional
        If DS9 is not running, attempt to execute it.
    """
    try:
        xpa.reset()
        ds9Cmd("iconify no; raise", False)
        ds9Cmd("wcs wcsa", False)         # include the pixel coordinates WCS (WCSA)

        v0, v1 = ds9Version().split('.')[0:2]
        global needShow
        needShow = False
        try:
            if int(v0) == 5:
                needShow = (int(v1) <= 4)
        except Exception:
            pass
    except Ds9Error as e:
        if not re.search('xpa', os.environ['PATH']):
            raise Ds9Error('You need the xpa binaries in your path to use ds9 with python')

        if not execDs9:
            raise Ds9Error

        if not shutil.which("ds9"):
            raise NameError("ds9 doesn't appear to be on your path")
        if "DISPLAY" not in os.environ:
            raise RuntimeError("$DISPLAY isn't set, so I won't be able to start ds9 for you")

        print("ds9 doesn't appear to be running (%s), I'll try to exec it for you" % e)

        os.system('ds9 &')
        for i in range(10):
            try:
                ds9Cmd(selectFrame(1), False)
                break
            except Ds9Error:
                print("waiting for ds9...\r", end="")
                sys.stdout.flush()
                time.sleep(0.5)
            else:
                print("                  \r", end="")
                break

        sys.stdout.flush()

        raise Ds9Error


class Ds9Event(interface.Event):
    """An event generated by a mouse or key click on the display.
    """

    def __init__(self, k, x, y):
        interface.Event.__init__(self, k, x, y)


class DisplayImpl(virtualDevice.DisplayImpl):
    """Virtual device display implementation.
    """

    def __init__(self, display, verbose=False, *args, **kwargs):
        virtualDevice.DisplayImpl.__init__(self, display, verbose)

    def _close(self):
        """Called when the device is closed.
        """
        pass

    def _setMaskTransparency(self, transparency, maskplane):
        """Specify DS9's mask transparency.

        Parameters
        ----------
        transparency : `int`
            Percent transparency.
        maskplane : `NoneType`
            If `None`, transparency is enabled. Otherwise, this parameter is
            ignored.
        """
        if maskplane is not None:
            print("ds9 is unable to set transparency for individual maskplanes" % maskplane,
                  file=sys.stderr)
            return
        ds9Cmd("mask transparency %d" % transparency, frame=self.display.frame)

    def _getMaskTransparency(self, maskplane):
        """Return the current DS9's mask transparency.

        Parameters
        ----------
        maskplane : unused
            This parameter does nothing.
        """
        selectFrame(self.display.frame)
        return float(ds9Cmd("mask transparency", get=True))

    def _show(self):
        """Uniconify and raise DS9.

        Notes
        -----
        Raises if ``self.display.frame`` doesn't exist.
        """
        ds9Cmd("raise", trap=False, frame=self.display.frame)

    def _mtv(self, image, mask=None, wcs=None, title=""):
        """Display an Image and/or Mask on a DS9 display.

        Parameters
        ----------
        image : subclass of `lsst.afw.image.Image`
            Image to display.
        mask : subclass of `lsst.afw.image.Mask`, optional
            Mask.
        wcs : `lsst.afw.geom.SkyWcs`, optional
            WCS of data
        title : `str`, optional
            Title of image.
        """

        for i in range(3):
            try:
                initDS9(i == 0)
            except Ds9Error:
                print("waiting for ds9...\r", end="")
                sys.stdout.flush()
                time.sleep(0.5)
            else:
                if i > 0:
                    print("                                     \r", end="")
                    sys.stdout.flush()
                break

        ds9Cmd(selectFrame(self.display.frame))
        ds9Cmd("smooth no")
        self._erase()

        if image:
            _i_mtv(image, wcs, title, False)

        if mask:
            maskPlanes = mask.getMaskPlaneDict()
            nMaskPlanes = max(maskPlanes.values()) + 1

            planes = {}  # build inverse dictionary
            for key in maskPlanes:
                planes[maskPlanes[key]] = key

            planeList = range(nMaskPlanes)
            usedPlanes = int(afwMath.makeStatistics(mask, afwMath.SUM).getValue())
            mask1 = mask.Factory(mask.getBBox())  # Mask containing just one bitplane

            colorGenerator = self.display.maskColorGenerator(omitBW=True)
            for p in planeList:
                if planes.get(p):
                    pname = planes[p]

                if not ((1 << p) & usedPlanes):  # no pixels have this bitplane set
                    continue

                mask1[:] = mask
                mask1 &= (1 << p)

                color = self.display.getMaskPlaneColor(pname)

                if not color:  # none was specified
                    color = next(colorGenerator)
                elif color.lower() == "ignore":
                    continue

                ds9Cmd("mask color %s" % color)
                _i_mtv(mask1, wcs, title, True)
    #
    # Graphics commands
    #

    def _buffer(self, enable=True):
        """Push and pop buffer size.

        Parameters
        ----------
        enable : `bool`, optional
            If `True` (default), push size; else pop it.
        """
        if enable:
            cmdBuffer.pushSize()
        else:
            cmdBuffer.popSize()

    def _flush(self):
        """Flush buffer.
        """
        cmdBuffer.flush()

    def _erase(self):
        """Erase all regions in current frame.
        """
        ds9Cmd("regions delete all", flush=True, frame=self.display.frame)

    def _dot(self, symb, c, r, size, ctype, fontFamily="helvetica", textAngle=None):
        """Draw a symbol onto the specified DS9 frame.

        Parameters
        ----------
        symb : `str`, or subclass of `lsst.afw.geom.ellipses.BaseCore`
            Symbol to be drawn. Possible values are:

            - ``"+"``: Draw a "+"
            - ``"x"``: Draw an "x"
            - ``"*"``: Draw a "*"
            - ``"o"``: Draw a circle
            - ``"@:Mxx,Mxy,Myy"``: Draw an ellipse with moments (Mxx, Mxy,
              Myy);(the ``size`` parameter is ignored)
            - An object derived from `lsst.afw.geom.ellipses.BaseCore`: Draw
              the ellipse (argument size is ignored)

            Any other value is interpreted as a string to be drawn.
        c : `int`
            Column to draw symbol [0-based coordinates].
        r : `int`
            Row to draw symbol [0-based coordinates].
        size : `float`
            Size of symbol.
        ctype : `str`
            the name of a colour (e.g. ``"red"``)
        fontFamily : `str`, optional
            String font. May be extended with other characteristics,
            e.g. ``"times bold italic"``.
        textAngle: `float`, optional
            Text will be drawn rotated by ``textAngle``.

        Notes
        -----
        Objects derived from `lsst.afw.geom.ellipses.BaseCore` include
        `~lsst.afw.geom.ellipses.Axes` and `lsst.afw.geom.ellipses.Quadrupole`.
        """
        cmd = selectFrame(self.display.frame) + "; "
        for region in ds9Regions.dot(symb, c, r, size, ctype, fontFamily, textAngle):
            cmd += 'regions command {%s}; ' % region

        ds9Cmd(cmd, silent=True)

    def _drawLines(self, points, ctype):
        """Connect the points.

        Parameters
        -----------
        points : `list` of (`int`, `int`)
            A list of points specified as (col, row).
        ctype : `str`
            The name of a colour (e.g. ``"red"``).
        """
        cmd = selectFrame(self.display.frame) + "; "
        for region in ds9Regions.drawLines(points, ctype):
            cmd += 'regions command {%s}; ' % region

        ds9Cmd(cmd)

    def _scale(self, algorithm, min, max, unit, *args, **kwargs):
        """Set image color scale.

        Parameters
        ----------
        algorithm : {``"linear"``, ``"log"``, ``"pow"``, ``"sqrt"``, ``"squared"``, ``"asinh"``, ``"sinh"``, ``"histequ"``}  # noqa: E501
            Scaling algorithm. May be any value supported by DS9.
        min : `float`
            Minimum value for scale.
        max : `float`
            Maximum value for scale.
        unit : `str`
            Ignored.
        *args
            Ignored.
        **kwargs
            Ignored
        """
        if algorithm:
            ds9Cmd("scale %s" % algorithm, frame=self.display.frame)

        if min in ("minmax", "zscale"):
            ds9Cmd("scale mode %s" % (min))
        else:
            if unit:
                print("ds9: ignoring scale unit %s" % unit)

            ds9Cmd("scale limits %g %g" % (min, max), frame=self.display.frame)
    #
    # Zoom and Pan
    #

    def _zoom(self, zoomfac):
        """Zoom frame by specified amount.

        Parameters
        ----------
        zoomfac : `int`
            DS9 zoom factor.
        """
        cmd = selectFrame(self.display.frame) + "; "
        cmd += "zoom to %d; " % zoomfac

        ds9Cmd(cmd, flush=True)

    def _pan(self, colc, rowc):
        """Pan frame.

        Parameters
        ----------
        colc : `int`
            Physical column to which to pan.
        rowc : `int`
            Physical row to which to pan.
        """
        cmd = selectFrame(self.display.frame) + "; "
        # ds9 is 1-indexed. Grrr
        cmd += "pan to %g %g physical; " % (colc + 1, rowc + 1)

        ds9Cmd(cmd, flush=True)

    def _getEvent(self):
        """Listen for a key press on a frame in DS9 and return an event.

        Returns
        -------
        event : `Ds9Event`
            Event with (key, x, y).
        """
        vals = ds9Cmd("imexam key coordinate", get=True).split()
        if vals[0] == "XPA$ERROR":
            if vals[1:4] == ['unknown', 'option', '"-state"']:
                pass  # a ds9 bug --- you get this by hitting TAB
            else:
                print("Error return from imexam:", " ".join(vals), file=sys.stderr)
            return None

        k = vals.pop(0)
        try:
            x = float(vals[0])
            y = float(vals[1])
        except Exception:
            x = float("NaN")
            y = float("NaN")

        return Ds9Event(k, x, y)


try:
    haveGzip
except NameError:
    # does gzip work?
    haveGzip = not os.system("gzip < /dev/null > /dev/null 2>&1")


def _i_mtv(data, wcs, title, isMask):
    """Internal routine to display an image or a mask on a DS9 display.

    Parameters
    ----------
    data : Subclass of `lsst.afw.image.Image` or `lsst.afw.image.Mask`
        Data to display.
    wcs : `lsst.afw.geom.SkyWcs`
        WCS of data.
    title : `str`
        Title of display.
    isMask : `bool`
        Is ``data`` a mask?
    """
    title = str(title) if title else ""

    if isMask:
        xpa_cmd = "xpaset %s fits mask" % getXpaAccessPoint()
        # ds9 mis-handles BZERO/BSCALE in uint16 data.
        # The following hack works around this.
        # This is a copy we're modifying
        if data.getArray().dtype == np.uint16:
            data |= 0x8000
    else:
        xpa_cmd = "xpaset %s fits" % getXpaAccessPoint()

    if haveGzip:
        xpa_cmd = "gzip | " + xpa_cmd

    pfd = os.popen(xpa_cmd, "w")

    ds9Cmd(flush=True, silent=True)

    try:
        afwDisplay.writeFitsImage(pfd.fileno(), data, wcs, title)
    except Exception as e:
        try:
            pfd.close()
        except Exception:
            pass

        raise e

    try:
        pfd.close()
    except Exception:
        pass
