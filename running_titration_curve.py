#!/usr/bin/env python

"""
This script will calculate a pKa as a function of time fitting to a titration
curve
"""

import os, sys, re, math

# Make sure we have numpy and scipy
try:
   import numpy as np
   from scipy import optimize
   from scipy import __version__ as sp_version
except ImportError:
   print >> sys.stderr, 'Error: running_titration_curve.py depends on both ' + \
                        'numpy and scipy. Quitting'
   sys.exit(1)

# Make sure we have a version of scipy with curve_fit
if not hasattr(optimize, 'curve_fit'):
   print >> sys.stderr, ('Error: Your version of scipy [%s] does not have ' + \
         'curve_fit. You need at least scipy version 0.9.0') % sp_version
   sys.exit(1)

#-------------------------------------------------------------------------------

class pHStatFile(object):
   """ This loads a running pH statistics file """
   # Regular expressions for extracting info from the running pH stat file
   cumulativere = re.compile('========================== CUMULATIVE')
   solvphre = re.compile(r'Solvent pH is *([-+]?\d+\.\d+)')
   reslinere = re.compile(r'([A-Z4]+) *(\d+) *: Offset *([-+]?\d+(?:\.\d*)?|\.\d+|-*[Ii]nf) *Pred *([-+]?\d+(?:\.\d*)?|\.\d+|-*[Ii]nf) *Frac Prot *(\d+(?:\.\d*)?) *Transitions *(\d+)')
   
   def __init__(self, infile):
      """
      Constructor for pHStatFile:
         .  infile should be a "file" type object
      """
      self.f = infile
      # Search the file for the pH, then rewind the file
      self.pH = pHStatFile.get_pH(self)
      self.f.seek(0)
      # Get the list of titrating residues, then rewind the file
      self.list_of_residues = pHStatFile.titrating_residues(self)
      self.f.seek(0)

   def get_pH(self):
      """ Searches the beginning of the file for the pH """
      rawline = self.f.readline()
      while rawline:
         rematch = self.solvphre.match(rawline)
         if rematch:
            return float(rematch.groups()[0])
         rawline = self.f.readline()

   def titrating_residues(self):
      """
      Finds out which residues are titrating (i.e., have statistics printed in
      this file)
      """
      list_of_residues = []
      resname, resnum, frac_prot = self.get_next_residue()
      while not '%s_%d' % (resname, resnum) in list_of_residues:
         list_of_residues.append('%s_%d' % (resname, resnum))
         resname, resnum, frac_prot = self.get_next_residue()
      return list_of_residues

   def get_next_residue(self):
      """
      This command gets the next residue from this file.
      Returns a tuple: (resname, resnum, frac_prot)
      """
      rawline = self.f.readline()
      while rawline:
         rematch = self.reslinere.match(rawline)
         if rematch:
            return (rematch.groups()[0], int(rematch.groups()[1]),
                    float(rematch.groups()[4]))
         # If we make it to a blank line, keep skipping forward until we hit
         # another CUMULATIVE record
         elif not rawline.strip():
            rematch2 = self.cumulativere.match(rawline)
            while not rematch2:
               rawline = self.f.readline()
               # Check if we hit EOF
               if not rawline: return (None, None, None)
               rematch2 = self.cumulativere.match(rawline)
            # end while not rematch2
         rawline = self.f.readline()
      # If we hit here, we are out of lines, or something
      return (None, None, None)

#-------------------------------------------------------------------------------

def curve_with_hillcoef(ph, pka, hillcoef):
   """ Callable function with a variable Hill coefficient """
   return hillcoef * ph - pka

#-------------------------------------------------------------------------------

def curve_no_hillcoef(ph, pka):
   """ Callable function with a fixed Hill coefficient of 1 """
   return ph - pka

#-------------------------------------------------------------------------------

def hillize(frac_prot):
   """
   This function converts a fraction protonated into the value plotted in a Hill
   plot. A fraction protonated of 1 is -infinity, whereas 0 is +infinity
   """
   if frac_prot == 1: return '-inf'
   if frac_prot == 0: return 'inf'
   return math.log10((1-frac_prot)/frac_prot)

#-------------------------------------------------------------------------------

def main(file_list, outname, fit_func):
   """
   This function is the main driver. It fits the data to the given fit_func (it
   should be one of the Callable functions defined above).
   
   Variable explanations:
      file_list:     List of input files with running titration data
      outname:       File prefix to dump all of the statistics to
      fit_func:      The function we're fitting to

   All error checking should be done on this input before calling main, or
   suffer the exceptions! Output files are named "outname_RES_NUM.dat"
   """
   
   xdata = np.zeros(len(file_list))
   ydata = np.zeros(len(file_list))
   # Convert the file_list into a list of pHStatFile objects if it's not yet
   if type(file_list[0]).__name__ == 'str':
      tmp = [pHStatFile(open(fname, 'r')) for fname in file_list]
      file_list = tmp
      del tmp
   # Build the list of output files
   output_files = {}
   for resid in file_list[0].list_of_residues:
      output_files[resid] = open('%s_%s.dat' % (outname, resid), 'w')
  
   # Generate the x-data (the pHs). This never changes
   for i, frec in enumerate(file_list): xdata[i] = frec.pH

   # Now loop through all of our data
   numres = 0      # Number of residues we've looped through so far
   numframes = 0   # Number of frames we've looped through so far
   while True:
      numres += 1
      # If we've looped through all of our residues, then we know we've hit the
      # next frame, so update our counters accordingly
      if numres % len(output_files) == 0:
         numframes += 1
         numres = 1
      # Zero out the y-data, because we're about to fill it up
      ydata = np.zeros(len(file_list))
      for i, frec in enumerate(file_list):
         stuff = frec.get_next_residue()
         if not stuff: break
         resname, resnum, ydata[i] = stuff
         # Make the y-data into a hill-plottable form
         ydata[i] = hillize(ydata[i])
      if not stuff: break
      try:
         params, covariance = optimize.curve_fit(fit_func, xdata, ydata)
      except (RuntimeError, ValueError):
         # If we can't fit the data (expected at the very beginning), just go on
         continue
      # Now write out the data as: Frame # pKa1 std.dev. [hill.coef. std.dev.]
      # but only write out if we actually got a pKa this time around
      ofile = output_files['%s_%d' % (resname, resnum)]
      line = '%d ' % numframes
      try:
         for i, param in enumerate(params):
            line += '%.4f %.4f ' % (param, math.sqrt(covariance[i][i]))
         ofile.write(line + os.linesep)
      except ValueError:
         continue

if __name__ == '__main__':
   """ Main program """
   from optparse import OptionParser, OptionGroup
   
   usage = '%prog [Options] <pH_data1> <pH_data2> ... <pH_dataN>'
   epilog = ('This program will generate running pKa values with error bars ' +
             'taken from the quality of the fit.')

   parser = OptionParser(usage=usage, epilog=epilog)
   group = OptionGroup(parser, 'Fitting Options',
                       'These options control how the data are fit')
   group.add_option('-i', '--hill-coefficient', dest='hill', default=False,
                    action='store_true',
                    help='Fit allowing the Hill coefficient to change.' +
                    'Default behavior is to fix the Hill coefficient to 1.')
   group.add_option('-n', '--no-hill-coefficient', dest='hill',
                    action='store_false',
                    help='Fix the Hill coefficient to 1. Default behavior.')
   parser.add_option_group(group)
   group = OptionGroup(parser, 'Output Options', 'THese options control output')
   group.add_option('-o', '--output', dest='outprefix', metavar='FILE_PREFIX',
                    default='running_pkas',
                    help='Prefix to apply to output files. The output files ' +
                    'will be named FILE_PREFIX_[resname]_[resnum].dat where ' +
                    'resname is the residue name of each titratable residue ' +
                    'and resnum is the residue number of that residue. ' +
                    'Default (%default)')
   parser.add_option_group(group)

   opt, args = parser.parse_args()

   # Check that we have input data files
   if not args:
      print >> sys.stderr, 'Error: Missing pH data files'
      parser.print_help()
      sys.exit(1)
   # Check that all files exist
   for fname in args:
      if not os.path.exists(fname):
         print >> sys.stderr, 'Error: File [%s] cannot be found!' % fname
         sys.exit(1)
   # Select our fitting function
   fit_func = curve_no_hillcoef
   if opt.hill:
      fit_func = curve_with_hillcoef
   # Now call our main function
   main(args, opt.outprefix, fit_func)
