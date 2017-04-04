#!/usr/bin/env python3

import os
import sys
import glob
from subprocess import Popen, PIPE, TimeoutExpired


class Logger(object):
    def __init__(self, output=sys.stdout):
        self.output = output

    def __call__(self, fmt, *args):
        self.output.write((fmt + '\n').format(*args))


class NullLogger(Logger):
    def __call__(self, fmt, *args):
        pass


class CompilationUnit(object):
    def __init__(self, command, filename, *args,
                 timeout=5, cwd=None,
                 precall=None, postcall=None,
                 logger=NullLogger(),
                 return_codes={"ok": [0], "warn": []}):
        self.command = [command, *args, filename]
        self.timeout = timeout
        self.cwd = cwd
        def nullfn(): pass
        self.precall = precall if callable(precall) else nullfn
        self.postcall = postcall if callable(postcall) else nullfn
        for i in ("ok", "warn"):
            if i not in return_codes.keys():
                return_codes.update({i: []})
        self.return_codes = return_codes
        self.log = logger

    def _deal_timeout(self, process):
        self.log('Timeout expired')
        process.terminate()

        if process.poll():
            self.log('Process will not terminate, we kill it')
            process.kill()

        return process.communicate()

    def _deal_return_code(self, process, out, err):
        message = "Process '{}' exited with status '{}', stdout:'{}', stderr: '{}'".format(
                    ' '.join(self.command), process.returncode, str(out).replace(r'\n', '\n'), str(err).replace(r'\n', '\n'))
        if process.returncode not in self.return_codes["ok"] and \
        process.returncode not in self.return_codes["warn"]:
            raise RuntimeError(message)
        if process.returncode in self.return_codes["warn"]:
            self.log(message)

    def _run_process(self):
        process = Popen(self.command, stdout=PIPE, stderr=PIPE, cwd=self.cwd)
        try:
            out, err = process.communicate(timeout=self.timeout)
        except TimeoutExpired:
            out, err = self._deal_timeout(process)

        self._deal_return_code(process, out, err)

        return out, err

    def __call__(self):
        self.precall()
        out, err = self._run_process()
        self.postcall()

        return out, err


class CompilationProcess(object):
    def __init__(self):
        self.elements = []

    def add(self, element):
        if not callable(element):
            raise TypeError("argument {} is not callable".format(element))

        self.elements.append(element)

    def compile(self):
        for unit in self.elements:
            unit()


class PdfLatexCompiler(object):
    def command(self):
        return 'pdflatex'

    def _alternate_builddir_options(self, builddir):
        return ['-aux-directory={}'.format(builddir), '-output-directory={}'.format(builddir)]

    def arguments(self, options):
        opts = []

        if 'builddir' in options:
            opts += self._alternate_builddir_options(os.path.abspath(options['builddir']))

        return opts


class Project(object):
    def __init__(self, texoptions={}):
        self.latex = getattr(__import__('__main__'), texoptions['latex'])()
        self.bibtex = texoptions['bibtex']

        self.filepath = os.path.abspath(texoptions['maintex'])
        if 'builddir' in texoptions:
            self.builddir = os.path.abspath(texoptions['builddir'])
        else:
            self.builddir = self.path()

        self.texargs = self.latex.arguments(texoptions)

        self.log = getattr(__import__('__main__'), texoptions['logger'])()

    def path(self):
        return os.path.dirname(self.filepath)

    def main_texfile(self):
        return os.path.basename(self.filepath)

    def bibfiles(self):
        return glob.glob("{}/*.bib".format(self.path()))

    def has_bibtex(self):
        return bool(self.bibfiles())

    def reference_auxiliary_filename(self):
        return self.main_texfile()[:-3] + 'aux'

    def main_file_compilation(self):
        def main_file_log():
            self.log("compiling tex file '{}'", self.filepath)
        return CompilationUnit(self.latex.command(), self.filepath,
                               cwd=self.path(), precall=main_file_log,
                               logger=self.log, *self.texargs)

    def reference_compilation_units(self):
        def create_bibfile_symlinks():
            if self.builddir and (self.builddir != self.path()):
                for bibfile in self.bibfiles():
                    target = os.path.join(self.builddir, os.path.basename(bibfile))
                    if not os.path.exists(target):
                        self.log("creating symlink from '{}' to '{}'", bibfile, target)
                        os.symlink(bibfile, target)

        def reference_log():
            self.log("compiling auxiliary reference file '{}'", os.path.join(self.builddir, self.reference_auxiliary_filename()))

        return create_bibfile_symlinks, CompilationUnit(self.bibtex, self.reference_auxiliary_filename(),
                                                        cwd=self.builddir, precall=reference_log,
                                                        logger=self.log, return_codes={"ok": [0], "warn": [2]})

    def _generate_compilation(self):
        compilation = CompilationProcess()

        if self.builddir:
            def create_build_dir():
                if not os.path.exists(self.builddir):
                    self.log("creating build directory '{}'", self.builddir)
                    os.mkdir(self.builddir)
            compilation.add(create_build_dir)

        compilation.add(self.main_file_compilation())

        if self.has_bibtex():
            for unit in self.reference_compilation_units():
                compilation.add(unit)
            compilation.add(self.main_file_compilation())
            compilation.add(self.main_file_compilation())

        return compilation

    def compile(self):
        self._generate_compilation().compile()


def main(argc, argv):
    configs = {
        'latex': 'PdfLatexCompiler',
        'bibtex': 'bibtex',
        'maintex': None,
        'logger': 'Logger',
        'builddir': 'texbuild',
    }

    if argc < 2:
        try:
            with open("compiletexrc", "r") as rc:
                lines = rc.readlines()
                lines = filter(lambda line: line.split('=')[0].strip() in configs.keys(), lines)
                for line in lines:
                    key, val = tuple(line.split('='))
                    configs[key.strip()] = val.strip()
        except:
            raise RuntimeError("no tex file provided")
    else:
        configs['maintex'] = argv[1]

    Project(texoptions=configs).compile()


if __name__ == '__main__':
    main(len(sys.argv), sys.argv)
