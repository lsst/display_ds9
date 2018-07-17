/*
 * LSST Data Management System
 *
 * This product includes software developed by the
 * LSST Project (http://www.lsst.org/).
 * See the COPYRIGHT file
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the LSST License Statement and
 * the GNU General Public License along with this program.  If not,
 * see <https://www.lsstcorp.org/LegalNotices/>.
 */
#include "pybind11/pybind11.h"

#include "xpa.h"
#include "lsst/pex/exceptions/Runtime.h"

namespace py = pybind11;
using namespace pybind11::literals;

namespace lsst {
namespace display {
namespace ds9 {

namespace {

class myXPA {
public:
    static XPA get(bool reset = false) {
        static myXPA *singleton = NULL;

        if (reset && singleton != NULL) {
            delete singleton;
            singleton = NULL;
        }

        if (singleton == NULL) {
            singleton = new myXPA("w");
        }

        return singleton->_xpa;
    }

private:
    myXPA(myXPA &) = delete;
    myXPA operator=(myXPA const &) = delete;

    myXPA(char const *mode) {
        _xpa = XPAOpen((char *)mode);

        if (_xpa == NULL) {
            throw LSST_EXCEPT(lsst::pex::exceptions::IoError, "Unable to open XPA");
        }
    }

    ~myXPA() { XPAClose(_xpa); }

    static XPA _xpa;  // the real XPA connection
};

XPA myXPA::_xpa = NULL;

/*
 * A binding for XPAGet that talks to only one server, but doesn't have to talk (char **) with SWIG
 */
const char *XPAGet1(XPA xpa, char *xtemplate, char *paramlist, char *mode) {
    char *buf = NULL;   /* desired response */
    size_t len = 0;     /* length of buf; ignored */
    char *error = NULL; /* returned error if any*/

    if (xpa == NULL) {
        xpa = myXPA::get();
    }

    int n = XPAGet(xpa, xtemplate, paramlist, mode, &buf, &len, NULL, &error, 1);

    if (n == 0) {
        throw LSST_EXCEPT(lsst::pex::exceptions::IoError, "XPAGet returned 0");
    }
    if (error != NULL) {
        return error;
    }
    if (buf == NULL) {
        throw LSST_EXCEPT(lsst::pex::exceptions::IoError, "XPAGet returned a null buffer pointer");
    }

    return (buf);
}

const char *XPASet1(XPA xpa, char *xtemplate, char *paramlist, char *mode,
                    char *buf,     // desired extra data
                    int len = -1)  // length of buf (or -1 to compute automatically)
{
    if (len < 0) {
        len = strlen(buf);  // length of buf
    }
    char *error = NULL;  // returned error if any

    if (xpa == NULL) {
        xpa = myXPA::get();
    }

    int n = XPASet(xpa, xtemplate, paramlist, mode, buf, len, NULL, &error, 1);

    if (n == 0) {
        throw LSST_EXCEPT(lsst::pex::exceptions::IoError, "XPASet returned 0");
    }
    if (error != NULL) {
        return error;
    }

    return "";
}

const char *XPASetFd1(XPA xpa, char *xtemplate, char *paramlist, char *mode,
                      int fd) /* file descriptor for xpa to read */
{
    char *error = NULL; /* returned error if any*/

    if (xpa == NULL) {
        xpa = myXPA::get();
    }

    int n = XPASetFd(xpa, xtemplate, paramlist, mode, fd, NULL, &error, 1);

    if (n == 0) {
        throw LSST_EXCEPT(lsst::pex::exceptions::IoError, "XPASetFd returned 0");
    }
    if (error != NULL) {
        return error;
    }
    return "";
}

void reset() { myXPA::get(true); }

}  // <anonymous>

PYBIND11_MODULE(xpa, mod) {
    py::module::import("lsst.pex.exceptions");

    py::class_<xparec> cls(mod, "xparec");
    cls.def(py::init<>());

    mod.def("get", &XPAGet1, "xpa"_a, "xtemplate"_a, "paramList"_a, "mode"_a);
    mod.def("reset", &reset);
    mod.def("set", &XPASet1, "xpa"_a, "xtemplate"_a, "paramList"_a, "mode"_a, "buf"_a, "len"_a = -1);
    mod.def("setFd1", &XPASetFd1, "xpa"_a, "xtemplate"_a, "paramList"_a, "mode"_a, "fd"_a);
}

}  // ds9
}  // display
}  // lsst
