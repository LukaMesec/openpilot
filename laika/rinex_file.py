#!/usr/bin/env python

# Copyright (C) 2014 Swift Navigation Inc.
#
# This source is subject to the license found in the file 'LICENSE' which must
# be be distributed together with this source. All other rights reserved.
#
# THIS CODE AND INFORMATION IS PROVIDED "AS IS" WITHOUT WARRANTY OF ANY KIND,
# EITHER EXPRESSED OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND/OR FITNESS FOR A PARTICULAR PURPOSE.

import datetime
import numpy as np


def floatornan(x):
  if x == '' or x[-1] == ' ':
    return np.NaN
  else:
    return float(x)


def digitorzero(x):
  if x == ' ' or x == '':
    return 0
  else:
    return int(x)


def padline(l, n=16):
  x = len(l)
  x_ = n * ((x + n - 1) // n)
  padded = l + ' ' * (x_ - x)
  while len(padded) < 70:
    padded += ' ' * 16
  return padded


TOTAL_SATS = 132  # Increased to support Galileo


class RINEXFile:
  def __init__(self, filename):
    try:
      with open(filename, 'r') as f:
        self._read_header(f)
        self._read_data(f)
    except TypeError:
      print("TypeError, file likely not downloaded.")
      raise SystemExit(-1)
    except FileNotFoundError:
      print("File not found in directory.")
      raise SystemExit(-1)
  def _read_header(self, f):
    version_line = padline(f.readline(), 80)

    self.version = float(version_line[0:9])
    if (self.version > 2.11):
      raise ValueError(
        "RINEX file versions > 2.11 not supported (file version %f)" % self.version)

    self.filetype = version_line[20]
    if self.filetype not in "ONGM":  # Check valid file type
      raise ValueError("RINEX file type '%s' not supported" % self.filetype)
    if self.filetype != 'O':
      raise ValueError("Only 'OBSERVATION DATA' RINEX files are currently supported")

    self.gnss = version_line[40]
    if self.gnss not in " GRSEM":  # Check valid satellite system
      raise ValueError("Satellite system '%s' not supported" % self.filetype)
    if self.gnss == ' ':
      self.gnss = 'G'
    if self.gnss != 'G':
      #raise ValueError("Only GPS data currently supported")
      pass

    self.comment = ""
    while True:  # Read the rest of the header
      line = padline(f.readline(), 80)
      label = line[60:80].rstrip()
      if label == "END OF HEADER":
        break
      if label == "COMMENT":
        self.comment += line[:60] + '\n'
      if label == "MARKER NAME":
        self.marker_name = line[:60].rstrip()
        if self.marker_name == '':
          self.marker_name = 'UNKNOWN'
      if label == "# / TYPES OF OBSERV":
        # RINEX files can have multiple line headers
        # This code handles the case
        try:
          n_obs = int(line[0:6])
          self.obs_types = []
        except ValueError:
          pass

        if n_obs <= 9:
          for i in range(0, n_obs):
            self.obs_types.append(line[10 + 6 * i:12 + 6 * i])
        if n_obs > 9:
          for i in range(0, 9):
            self.obs_types.append(line[10 + 6 * i:12 + 6 * i])
          n_obs -= 9

  def _read_epoch_header(self, f):
    epoch_hdr = f.readline()
    if epoch_hdr == '':
      return None
    if epoch_hdr.find('0.0000000  4  5') != -1:
      epoch_hdr = f.readline()
    if epoch_hdr.find('MARKER NUMBER') != -1:
      epoch_hdr = f.readline()
    for i in range(5):
      if epoch_hdr.find('COMMENT') != -1:
        epoch_hdr = f.readline()
    if epoch_hdr.find('          4  1') != -1:
      epoch_hdr = f.readline()

    year = int(epoch_hdr[1:3])
    if year >= 80:
      year += 1900
    else:
      year += 2000
    month = int(epoch_hdr[4:6])
    day = int(epoch_hdr[7:9])
    hour = int(epoch_hdr[10:12])
    minute = int(epoch_hdr[13:15])
    second = int(epoch_hdr[15:18])
    microsecond = int(
      epoch_hdr[19:25])  # Discard the least sig. fig. (use microseconds only).
    epoch = datetime.datetime(year, month, day, hour, minute, second, microsecond)

    flag = int(epoch_hdr[28])
    if flag != 0:
      raise ValueError("Don't know how to handle epoch flag %d in epoch header:\n%s",
                       (flag, epoch_hdr))

    n_sats = int(epoch_hdr[29:32])
    sats = []
    for i in range(0, n_sats):
      if ((i % 12) == 0) and (i > 0):
        epoch_hdr = f.readline()
      sats.append(epoch_hdr[(32 + (i % 12) * 3):(35 + (i % 12) * 3)])

    return epoch, flag, sats

  def _read_obs(self, f, n_sat, sat_map):
    obs = np.empty((TOTAL_SATS, len(self.obs_types)), dtype=np.float64) * np.NaN
    lli = np.zeros((TOTAL_SATS, len(self.obs_types)), dtype=np.uint8)
    signal_strength = np.zeros((TOTAL_SATS, len(self.obs_types)), dtype=np.uint8)

    for i in range(n_sat):
      # Join together observations for a single satellite if split across lines.
      obs_line = ''.join(
        padline(f.readline()[:-1], 16) for _ in range((len(self.obs_types) + 4) // 5))
      for j in range(len(self.obs_types)):
        obs_record = obs_line[16 * j:16 * (j + 1)]
        obs[int(sat_map[i]), j] = floatornan(obs_record[0:14])
        lli[int(sat_map[i]), j] = digitorzero(obs_record[14:15])
        signal_strength[int(sat_map[i]), j] = digitorzero(obs_record[15:16])

    return obs, lli, signal_strength

  def _read_data_chunk(self, f, CHUNK_SIZE=10000):
    obss = np.empty(
      (CHUNK_SIZE, TOTAL_SATS, len(self.obs_types)), dtype=np.float64) * np.NaN
    llis = np.zeros((CHUNK_SIZE, TOTAL_SATS, len(self.obs_types)), dtype=np.uint8)
    signal_strengths = np.zeros(
      (CHUNK_SIZE, TOTAL_SATS, len(self.obs_types)), dtype=np.uint8)
    epochs = np.zeros(CHUNK_SIZE, dtype='datetime64[us]')
    flags = np.zeros(CHUNK_SIZE, dtype=np.uint8)

    i = 0
    while True:
      hdr = self._read_epoch_header(f)
      if hdr is None:
        break
      epoch, flags[i], sats = hdr
      epochs[i] = np.datetime64(epoch)
      sat_map = np.ones(len(sats)) * -1
      for n, sat in enumerate(sats):
        if sat[0] == 'G':
          sat_map[n] = int(sat[1:]) - 1
        if sat[0] == 'R':
          sat_map[n] = int(sat[1:]) - 1 + 64
      obss[i], llis[i], signal_strengths[i] = self._read_obs(f, len(sats), sat_map)
      i += 1
      if i >= CHUNK_SIZE:
        break

    return obss[:i], llis[:i], signal_strengths[:i], epochs[:i], flags[:i]

  def _read_data(self, f):
    'obs_data_chunks = []
    self.data = {}
    while True:
      obss, llis, signal_strengths, epochs, flags = self._read_data_chunk(f)
      if obss.shape[0] == 0:
        break

      for i, sv in enumerate(['%02d' % d for d in range(1, TOTAL_SATS+1)]):
        if sv not in self.data:
          self.data[sv] = {}
        for j, obs_type in enumerate(self.obs_types):
          if obs_type in self.data[sv]:
            self.data[sv][obs_type] = np.append(self.data[sv][obs_type], obss[:, i, j])
          else:
            self.data[sv][obs_type] = obss[:, i, j]
        if 'Epochs' in self.data[sv]:
          self.data[sv]['Epochs'] = np.append(self.data[sv]['Epochs'], epochs)
        else:
          self.data[sv]['Epochs'] = epochs
    for sat in list(self.data.keys()):
      if np.all(np.isnan(self.data[sat]['C1'])):
        del self.data[sat]














