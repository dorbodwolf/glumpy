# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# Copyright (c) 2014, Nicolas P. Rougier. All rights reserved.
# Distributed under the terms of the new BSD License.
# -----------------------------------------------------------------------------
import re
import os.path
import numpy as np

from glumpy import gl
from glumpy.log import log
from glumpy.gloo.globject import GLObject


# ------------------------------------------------------------ Shader class ---
class Shader(GLObject):
    """Abstract shader class."""

    _gtypes = {
        'float':       gl.GL_FLOAT,
        'vec2':        gl.GL_FLOAT_VEC2,
        'vec3':        gl.GL_FLOAT_VEC3,
        'vec4':        gl.GL_FLOAT_VEC4,
        'int':         gl.GL_INT,
        'ivec2':       gl.GL_INT_VEC2,
        'ivec3':       gl.GL_INT_VEC3,
        'ivec4':       gl.GL_INT_VEC4,
        'bool':        gl.GL_BOOL,
        'bvec2':       gl.GL_BOOL_VEC2,
        'bvec3':       gl.GL_BOOL_VEC3,
        'bvec4':       gl.GL_BOOL_VEC4,
        'mat2':        gl.GL_FLOAT_MAT2,
        'mat3':        gl.GL_FLOAT_MAT3,
        'mat4':        gl.GL_FLOAT_MAT4,
        'sampler1D':   gl.GL_SAMPLER_1D,
        'sampler2D':   gl.GL_SAMPLER_2D,
    }


    def __init__(self, target, code=None):
        """
        Initialize the shader and get code if possible.

        Parameters
        ----------

        code: str
            code can be a filename or the actual code
        """

        GLObject.__init__(self)
        if target not in [gl.GL_VERTEX_SHADER, gl.GL_FRAGMENT_SHADER]:
            raise ValueError("Shader target must be vertex or fragment")

        self._target = target
        self._code = None
        self._source = None
        if code is not None:
            self.code = code


    @property
    def code(self):
        """ Shader source code """
        return self._code

    @code.setter
    def code(self, code):
        """ Shader source code """

        if os.path.isfile(code):
            with open(code, 'rt') as file:
                self._code = file.read()
                self._source = os.path.basename(code)
        else:
            self._code   = code
            self._source = '<string>'
        self._need_update = True


    @property
    def source(self):
        """ Shader source (string or filename) """
        return self._source


    def _create(self):
        """ Compile the source and checks eveyrthing's ok """

        # Check if we have something to compile
        if not self._code:
            raise RuntimeError("No code has been given")

        # Check that shader object has been created
        if self._handle <= 0:
            self._handle = gl.glCreateShader(self._target)
            if self._handle <= 0:
                raise RuntimeError("Cannot create shader object")

        # Set shader source
        gl.glShaderSource(self._handle, self._code)

        log.debug("GPU: Creating shader")

        # Actual compilation
        gl.glCompileShader(self._handle)
        status = gl.glGetShaderiv(self._handle, gl.GL_COMPILE_STATUS)
        if not status:
            error = gl.glGetShaderInfoLog(self._handle)
            lineno, mesg = self._parse_error(error)
            self._print_error(mesg, lineno-1)
            raise RuntimeError("Shader compilation error")


    def _delete(self):
        """ Delete shader from GPU memory (if it was present). """

        gl.glDeleteShader(self._handle)


    def _parse_error(self, error):
        """
        Parses a single GLSL error and extracts the line number and error
        description.

        Parameters
        ----------
        error : str
            An error string as returned byt the compilation process
        """

        # Nvidia
        # 0(7): error C1008: undefined variable "MV"
        m = re.match(r'(\d+)\((\d+)\):\s(.*)', error )
        if m: return int(m.group(2)), m.group(3)

        # ATI / Intel
        # ERROR: 0:131: '{' : syntax error parse error
        m = re.match(r'ERROR:\s(\d+):(\d+):\s(.*)', error )
        if m: return int(m.group(2)), m.group(3)

        # Nouveau
        # 0:28(16): error: syntax error, unexpected ')', expecting '('
        m = re.match( r'(\d+):(\d+)\((\d+)\):\s(.*)', error )
        if m: return int(m.group(2)), m.group(4)

        raise ValueError('Unknown GLSL error format')


    def _print_error(self, error, lineno):
        """
        Print error and show the faulty line + some context

        Parameters
        ----------
        error : str
            An error string as returned byt the compilation process

        lineno: int
            Line where error occurs
        """
        lines = self._code.split('\n')
        start = max(0,lineno-3)
        end = min(len(lines),lineno+3)

        print('Error in %s' % (repr(self)))
        print(' -> %s' % error)
        print()
        if start > 0:
            print(' ...')
        for i, line in enumerate(lines[start:end]):
            if (i+start) == lineno:
                print(' %03d %s' % (i+start, line))
            else:
                if len(line):
                    print(' %03d %s' % (i+start,line))
        if end < len(lines):
            print(' ...')
        print()


    def _remove_comments(self, string):
        """ Remove C-style comment from a string """

        pattern = r"(\".*?\"|\'.*?\')|(/\*.*?\*/|//[^\r\n]*$)"
        # first group captures quoted strings (double or single)
        # second group captures comments (//single-line or /* multi-line */)
        regex = re.compile(pattern, re.MULTILINE|re.DOTALL)

        def do_replace(match):
            # if the 2nd group (capturing comments) is not None,
            # it means we have captured a non-quoted (real) comment string.
            if match.group(2) is not None:
                return "" # so we will return empty to remove the comment
            else: # otherwise, we will return the 1st group
                return match.group(1) # captured quoted-string

        return regex.sub(do_replace, string)


    @property
    def uniforms(self):
        """ Shader uniforms obtained from source code """

        # We take care of:  uniform float a;
        #                   uniform float a[3];
        #                   uniform float a, b, c;

        uniforms = []
        re_type = re.compile("""
                             \s*uniform         # Attribute declaration
                             \s+(?P<type>\w+)   # Attribute type
                             \s+(?P<names>[\w,\[\] ]+);  # Attributes name(s)
                             """, re.VERBOSE)
        re_names = re.compile("""
                              (?P<name>\w+)           # Attribute name
                              \s*(\[(?P<size>\d+)\])? # Attribute size
                              """, re.VERBOSE)
        code = self._remove_comments(self._code)
        for match in re.finditer(re_type, code):
            gtype = Shader._gtypes[match.group('type')]
            names = match.group('names')
            for match in re.finditer(re_names, names):
                name = match.group('name')
                size = match.group('size')
                if size is None:
                    uniforms.append((name, gtype))
                else:
                    size = int(size)
                    if size == 0:
                        raise RuntimeError("Size of uniform array cannot be zero")
                    for i in range(size):
                        iname = '%s[%d]' % (name,i)
                        uniforms.append((iname, gtype))

        return uniforms


    @property
    def attributes(self):
        """ Shader attributes obtained from source code """

        # We take care of:  attribute float a;
        #                   attribute float a[3];
        #                   attribute float a, b, c;

        attributes = []
        re_type = re.compile("""
                             \s*attribute         # Attribute declaration
                             \s+(?P<type>\w+)   # Attribute type
                             \s+(?P<names>[\w,\[\] ]+);  # Attributes name(s)
                             """, re.VERBOSE)
        re_names = re.compile("""
                              (?P<name>\w+)           # Attribute name
                              \s*(\[(?P<size>\d+)\])? # Attribute size
                              """, re.VERBOSE)
        code = self._remove_comments(self._code)

        for match in re.finditer(re_type, code):
            gtype = Shader._gtypes[match.group('type')]
            names = match.group('names')
            for match in re.finditer(re_names, names):
                name = match.group('name')
                size = match.group('size')
                if size is None:
                    attributes.append((name, gtype))
                else:
                    size = int(size)
                    if size == 0:
                        raise RuntimeError("Size of uniform array cannot be zero")
                    for i in range(size):
                        iname = '%s[%d]' % (name,i)
                        attributes.append((iname, gtype))

        return attributes



# ------------------------------------------------------ VertexShader class ---
class VertexShader(Shader):
    """ Vertex shader class """

    def __init__(self, code=None):
        Shader.__init__(self, gl.GL_VERTEX_SHADER, code)

    def __repr__(self):
        return "Vertex Shader %d (%s)" % (self._id, self._source)



# ---------------------------------------------------- FragmentShader class ---
class FragmentShader(Shader):
    """ Fragment shader class """


    def __init__(self, code=None):
        Shader.__init__(self, gl.GL_FRAGMENT_SHADER, code)


    def __repr__(self):
        return "Fragment Shader %d (%s)" % (self._id, self._source)