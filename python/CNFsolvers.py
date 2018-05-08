import array
import atexit
import bisect
import collections
import gzip
import os
import re
import subprocess
import tempfile
from pyminisolvers import minisolvers


class MinisatSubsetSolver:
    def __init__(self, infile, store_dimacs=False):
        self.s = minisolvers.MinisatSubsetSolver()
        self.store_dimacs = store_dimacs
        if self.store_dimacs:
            self.dimacs = []
            self.groups = collections.defaultdict(list)
        self.read_dimacs(infile)

    def parse_dimacs(self, f):
        i = 0
        for line in f:
            if line.startswith(b'p'):
                tokens = line.split()
                gcnf_in = (tokens[1] == b"gcnf")
                self.nvars = int(tokens[2])
                self.nclauses = int(tokens[3])

                # self.n = number of soft constraints
                if gcnf_in:
                    self.n = int(tokens[4])
                else:
                    self.n = self.nclauses

                self.s.set_varcounts(self.nvars, self.n)

                while self.s.nvars() < self.nvars:
                    # let instance variables do whatever...
                    self.s.new_var()
                while self.s.nvars() < self.nvars + self.n:
                    # but default relaxation variables to try to *enable*
                    # clauses (to find larger sat subsets and/or hit unsat
                    # sooner)
                    self.s.new_var(True)
                continue

            if line.startswith(b'c'):
                continue

            # anything else is a clause
            assert self.n > 0
            vals = line.split()
            assert vals[-1] == b'0'

            if gcnf_in:
                groupid = int(vals[0][1:-1])  # "parse" the '{x}' group ID
                assert 0 <= groupid <= self.n
                clause = [int(x) for x in vals[1:-1]]
            else:
                groupid = i+1
                clause = [int(x) for x in vals[:-1]]

            if groupid == 0:
                # add as a hard clause
                self.s.add_clause(clause)
            else:
                self.s.add_clause_instrumented(clause, groupid-1)

            if self.store_dimacs:
                if gcnf_in:
                    # need to reform clause without '{x}' group index
                    self.dimacs.append(b" ".join(str(x).encode() for x in clause) + b" 0\n")
                    self.groups[groupid].append(i)
                else:
                    self.dimacs.append(line)
                    self.groups[groupid] = [i]

            i += 1

        assert i == self.nclauses

    def read_dimacs(self, infile):
        if infile.name.endswith('.gz'):
            # use gzip to decompress
            infile.close()
            with gzip.open(infile.name) as gz_f:
                self.parse_dimacs(gz_f)
        else:
            # assume plain .cnf and pass through the file object
            self.parse_dimacs(infile)

    def check_subset(self, seed, improve_seed=False):
        is_sat = self.s.solve_subset(seed)
        if improve_seed:
            if is_sat:
                seed = self.s.sat_subset()
            else:
                seed = self.s.unsat_core()
            return is_sat, seed
        else:
            return is_sat

    def complement(self, aset):
        return set(range(self.n)).difference(aset)

    def shrink(self, seed, hard=[]):
        current = set(seed)
        for i in seed:
            if i not in current or i in hard:
                # May have been "also-removed"
                continue
            current.remove(i)
            if not self.check_subset(current):
                # Remove any also-removed constraints
                current = set(self.s.unsat_core())  # helps a bit
            else:
                current.add(i)
        return current

    def to_c_lits(self, seed):
        # this is slow...
        nv = self.nvars+1
        return [nv + i for i in seed]

    def check_above(self, seed):
        comp = self.complement(seed)
        x = self.s.new_var() + 1
        self.s.add_clause([-x] + self.to_c_lits(comp))  # add a temporary clause
        ret = self.s.solve([x] + self.to_c_lits(seed))  # activate the temporary clause and all seed clauses
        self.s.add_clause([-x])  # remove the temporary clause
        return ret

    def grow(self, seed, inplace):
        if inplace:
            current = seed
        else:
            current = seed[:]

        #while self.check_above(current):
        #    current = self.s.sat_subset()
        #return current

        # a bit slower at times, much faster others...
        for x in self.complement(current):
            # skip any included by sat_subset()
            # assumes seed is always sorted
            i = bisect.bisect_left(current, x)
            if i != len(current) and current[i] == x:
                continue

            current.append(x)
            if self.check_subset(current):
                # Add any also-satisfied constraint
                current = self.s.sat_subset()
            else:
                current.pop()

        return current


class MUSerException(Exception):
    pass


class MUSerSubsetSolver(MinisatSubsetSolver):
    def __init__(self, filename):
        MinisatSubsetSolver.__init__(self, filename, store_dimacs=True)
        self.core_pattern = re.compile(r'^v [\d ]+$', re.MULTILINE)
        self.muser_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'muser2-static')
        if not os.path.isfile(self.muser_path):
            raise MUSerException("MUSer2 binary not found at %s" % self.muser_path)
        try:
            # a bit of a hack to check whether we can really run it
            DEVNULL = open(os.devnull, 'wb')
            subprocess.Popen([self.muser_path], stdout=DEVNULL, stderr=DEVNULL)
        except:
            raise MUSerException("MUSer2 binary %s is not executable.\n"
                                 "It may be compiled for a different platform." % self.muser_path)

        self._proc = None  # track the MUSer process
        atexit.register(self.cleanup)

    # kill MUSer process if still running when we exit (e.g. due to a timeout)
    def cleanup(self):
        if self._proc:
            self._proc.kill()

    # write CNF output for MUSer2
    def write_CNF(self, cnffile, seed, hard):
        # Write CNF (grouped, with hard clauses, if any, in the 0 / Don't-care group)
        header = "p gcnf %d %d %d\n" % (self.nvars, len(seed), len(seed))
        cnffile.write(header.encode())

        # Note: not writing newlines because dimacs[j] already contains a newline

        # existing "Don't care" group
        for j in self.groups[0]:
            cnffile.write(b"{0} ")  # {0} = "Don't care" group
            cnffile.write(self.dimacs[j])
        # also include hard clauses in "Don't care" group
        for i in hard:
            for j in self.groups[i+1]:
                cnffile.write(b"{0} ")
                cnffile.write(self.dimacs[j])

        for g, i in enumerate(seed):
            if i in hard:
                # skip hard clauses
                continue
            for j in self.groups[i+1]:
                cnffile.write(("{%d} " % (g+1)).encode())
                cnffile.write(self.dimacs[j])

        cnffile.flush()

    # override shrink method to use MUSer2
    # NOTE: seed must be indexed (i.e., not a set)
    def shrink(self, seed, hard=[]):
        # Open tmpfile
        with tempfile.NamedTemporaryFile('wb') as cnf:
            self.write_CNF(cnf, seed, hard)

            # Run MUSer
            self._proc = subprocess.Popen([self.muser_path, '-comp', '-grp', '-v', '-1', cnf.name],
                                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            out, err = self._proc.communicate()
            self._proc = None  # clear it when we're done (so cleanup won't try to kill it)
            out = out.decode()

        # Parse result, return the core
        matchline = re.search(self.core_pattern, out).group(0)
        ret = array.array('i', (seed[int(x)-1] for x in matchline.split()[1:-1]) )

        # Add back in hard clauses
        ret.extend(hard)

        return ret
