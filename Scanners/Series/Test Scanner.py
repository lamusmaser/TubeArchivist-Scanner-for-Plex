#!/usr/bin/env python

"""
Custom scanner plugin for Plex Media Server for transferred Tivo recordings.
"""

import re, os, os.path
import sys
import inspect
import time
import ssl
import datetime
import logging, logging.handlers
from lxml import etree
try:
  from ssl import PROTOCOL_TLS as SSL_PROTOCOL # Python >= 2.7.13 #ssl.PROTOCOL_TLSv1
except ImportError:  
  from ssl import PROTOCOL_SSLv23 as SSL_PROTOCOL # Python <  2.7.13
try:
  from urllib.request import urlopen, Request     # Python >= 3.0
except ImportError:
  from urllib2 import urlopen, Request     # Python == 2.x

# I needed some plex libraries, you may need to adjust your plex install location accordingly
PLEX_ROOT              = ""
PLEX_LIBRARY           = {}
PLEX_LIBRARY_URL       = "http://localhost:32400/library/sections/"  # Allow to get the library name to get a log per library https://support.plex.tv/hc/en-us/articles/204059436-Finding-your-account-token-X-Plex-Token

import Media, VideoFiles, Stack, Utils

SSL_CONTEXT            = ssl.SSLContext(SSL_PROTOCOL)
FILTER_CHARS    = "\\/:*?<>|;"  #_.~  
youtube_regexs = [
  '[0-9]{8}_[a-zA-Z0-9]{11}_*.*'    # YYYYMMDD_XXXXXXXXXXX_TITLE.ext
]


### Setup core variables ################################################################################
def setup():
  with open("/tmp/test-output.log","a") as f:
    global SetupDone
    if SetupDone:  return
    else:          SetupDone = True
    f.write("SetupDone is set.")

  ### Define PLEX_ROOT ##################################################################################
  with open("/tmp/test-output.log",'a') as f:
    global PLEX_ROOT
    PLEX_ROOT = os.path.abspath(os.path.join(os.path.dirname(inspect.getfile(inspect.currentframe())), "..", ".."))
    f.write("Testing Initial PLEX_ROOT: " + PLEX_ROOT)
    if not os.path.isdir(PLEX_ROOT):
        path_location = { 'Windows': '%LOCALAPPDATA%\\Plex Media Server',
                        'MacOSX':  '$HOME/Library/Application Support/Plex Media Server',
                        'Linux':   '$PLEX_HOME/Library/Application Support/Plex Media Server',
                        'Android': '/storage/emulated/0/Plex Media Server' }
        PLEX_ROOT = os.path.expandvars(path_location[Platform.OS.lower()] if Platform.OS.lower() in path_location else '~')  # Platform.OS:  Windows, MacOSX, or Linux
        f.write("Platform review required, Platform: " + Platform.OS.lower() + " and the new PLEX_ROOT: " + PLEX_ROOT)

  ### Define logging setup ##############################################################################
  if sys.version[0] == '2':
    from imp import reload
    reload(sys)
    sys.setdefaultencoding("utf-8")
  global Log
  Log = logging.getLogger('main')
  Log.setLevel(logging.DEBUG)
  set_logging()

  ### Populate PLEX_LIBRARY #############################################################################
  Log.info(u"".ljust(157, '='))
  Log.info(u"Plex scan started: {}".format(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S,%f")))
  try:
    library_xml = etree.fromstring(read_url(Request(PLEX_LIBRARY_URL, headers={"X-Plex-Token": read_file(os.path.join(PLEX_ROOT, "X-Plex-Token.id")).strip() if os.path.isfile(os.path.join(PLEX_ROOT, "X-Plex-Token.id")) else Dict(os.environ, 'PLEXTOKEN')})))
    for directory in library_xml.iterchildren('Directory'):
      for location in directory.iterchildren('Location'):
        PLEX_LIBRARY[location.get('path')] = {'title': directory.get('title'), 'scanner': directory.get("scanner"), 'agent': directory.get('agent')}
        Log.info(u'id: {:>2}, type: {:<6}, agent: {:<30}, scanner: {:<30}, library: {:<24}, path: {}'.format(directory.get("key"), directory.get('type'), directory.get("agent"), directory.get("scanner"), directory.get('title'), location.get("path")))
  except Exception as e:  Log.error("Exception: '%s', library_xml could not be loaded. X-Plex-Token file created?" % (e))
  Log.info(u"".ljust(157, '='))

### Read in a url #######################################################################################
def read_url(url, data=None):
  url_content = ""
  try:
    if data is None:  url_content = urlopen(url, context=SSL_CONTEXT).read()
    else:             url_content = urlopen(url, context=SSL_CONTEXT, data=data).read()
    return url_content
  except Exception as e:  Log.error("Error reading url '%s', Exception: '%s'" % (url, e)); raise e


### Read in a local file ################################################################################
def read_file(local_file):
  file_content = ""
  try:
    with open(local_file, 'r') as file:  file_content = file.read()
    return file_content
  except Exception as e:  Log.error("Error reading file '%s', Exception: '%s'" % (local_file, e)); raise e


### Set Logging #########################################################################################
def set_logging(root='', foldername='', filename='', backup_count=0, format='%(message)s', mode='a'):
  log_path = os.path.join(PLEX_ROOT, 'Logs', 'Test Scanner Logs')
  if not os.path.exists(log_path):  os.makedirs(log_path)
  if not foldername:                  foldername = Dict(PLEX_LIBRARY, root, 'title')  # If foldername is not defined, try and pull the library title from PLEX_LIBRARY
  if foldername:                      log_path = os.path.join(log_path, os_filename_clean_string(foldername))
  if not os.path.exists(log_path):  os.makedirs(log_path)

  filename = os_filename_clean_string(filename) if filename else '_root_.scanner.log'
  log_file = os.path.join(log_path, filename)

  # Bypass DOS path MAX_PATH limitation (260 Bytes=> 32760 Bytes, 255 Bytes per folder unless UDF 127B ytes max)
  if os.sep=="\\":
    dos_path = os.path.abspath(log_file) if isinstance(log_file, unicode) else os.path.abspath(log_file.decode('utf-8'))
    log_file = u"\\\\?\\UNC\\" + dos_path[2:] if dos_path.startswith(u"\\\\") else u"\\\\?\\" + dos_path

  #if not mode:  mode = 'a' if os.path.exists(log_file) and os.stat(log_file).st_mtime + 3600 > time.time() else 'w' # Override mode for repeat manual scans or immediate rescans

  global Handler
  if Handler:       Log.removeHandler(Handler)
  if backup_count:  Handler = logging.handlers.RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=backup_count, encoding='utf-8')
  else:             Handler = logging.FileHandler                 (log_file, mode=mode, encoding='utf-8')
  Handler.setFormatter(logging.Formatter(format))
  Handler.setLevel(logging.DEBUG)
  Log.addHandler(Handler)

#########################################################################################################
def Dict(var, *arg, **kwarg):
  """ Return the value of an (imbricated) dictionnary, if all fields exist else return "" unless "default=new_value" specified as end argument
      Ex: Dict(variable_dict, 'field1', 'field2', default = 0)
  """
  for key in arg:
    if isinstance(var, dict) and key and key in var:  var = var[key]
    else:  return kwarg['default'] if kwarg and 'default' in kwarg else ""   # Allow Dict(var, tvdbid).isdigit() for example
  return kwarg['default'] if var in (None, '', 'N/A', 'null') and kwarg and 'default' in kwarg else "" if var in (None, '', 'N/A', 'null') else var

### Sanitize string #####################################################################################
def os_filename_clean_string(string):
  for char, subst in zip(list(FILTER_CHARS), [" " for x in range(len(FILTER_CHARS))]) + [("`", "'"), ('"', "'")]:    # remove leftover parenthesis (work with code a bit above)
    if char in string:  string = string.replace(char, subst)                                                         # translate anidb apostrophes into normal ones #s = s.replace('&', 'and')
  return string

def filter_chars(string):
  for char, subst in zip(list(FILTER_CHARS), [" " for x in range(len(FILTER_CHARS))]):
    if char in string:  string = string.replace(char, subst)
  return string

# Look for episodes.
def Scan(path, files, mediaList, subdirs):
  setup()
  # Scan for video files.
  VideoFiles.Scan(path, files, mediaList, subdirs)
  
  # Take top two as show/season, but require at least the top one.
  paths = Utils.SplitPath(path)
  
  if len(paths) > 0 and len(paths[0]) > 0:
    done = False
        
    if done == False:

    #   # Not a perfect standalone match, so get information from directories. (e.g. "Lost/Season 1/s0101.mkv")
    #   season = None
    #   seasonNumber = None

      (show, year) = VideoFiles.CleanName(paths[0])
      
      for i in files:
        done = False
        file = os.path.basename(i)
        (file, ext) = os.path.splitext(file)
        
        # found = False
        for rx in youtube_regexs:
          match = re.search(rx, file, re.IGNORECASE)
          if match:
            originalAirDate = file[0:7]
            ytid = file[9:19]
            title = file[21:]
            season = originalAirDate[0:4]
            episode = originalAirDate[5:]
            tv_show = Media.Episode(show, season, episode, title, None)
            tv_show.parts.append(i)
            mediaList.append(tv_show)
            break


        # # See if there's a pytivo metadata file to peek at
        # meta = dict()
        # metadata_filename = '{0}.txt'.format(i.replace('_LQ', ''))
        # if os.path.isfile(metadata_filename):
        #   with open(metadata_filename, 'r') as f:
        #     for line in f:
        #       line = line.strip()
        #       if line and len(line):
        #         line_a = line.split(' : ')
        #         if len(line_a) > 1:
        #           key, value = line.split(' : ')
        #           meta[key] = value

        #print "pytivo metadata, ", meta

        # Skip tv shows based on pytivo metadata file and backup to filename if not present
        # is_movie = False
        # if 'isEpisode' in meta:
        #   if meta['isEpisode'] == 'false':
        #     is_movie = True
        # elif file.strip().startswith('(Rec'):
        #   is_movie = True

        # Skip tivo recorded movies
        # if is_movie == True:
        #   print "File {0} is determined to be a movie, skipping".format(file)
        #   continue

        # # Test for matching tivo server files
        # found = False
        # for rx in episode_regexps:
        #   match = re.search(rx, file, re.IGNORECASE)
        #   if match:
        #     season = int(match.group('season')) if match.group('season') and match.group('season') != '' else None
        #     episode = int(match.group('ep')) if match.group('ep') and match.group('ep') != '' else None
        #     try:
        #       title = match.group('title') if match.group('title') else None
        #     except IndexError:
        #       title = None
            
        #     if 'episodeTitle' in meta:
        #       title = meta['episodeTitle']
        #     if 'seriesTitle' in meta:
        #       show = meta['seriesTitle']
        #     originalAirDate = None
        #     if 'originalAirDate' in meta:
        #       originalAirDate = meta['originalAirDate'].split('T')[0]
        #     if season is None and episode is None and title is None:
        #       continue
        #     if season is None and originalAirDate:
        #       season = int(originalAirDate.split('-')[0])
        #     found = True
        #     tv_show = Media.Episode(show, season, episode, title, None)
        #     if originalAirDate is not None:
        #       tv_show.released_at = originalAirDate
        #     tv_show.parts.append(i)
        #     mediaList.append(tv_show)
        #     break
        # if found == True:
        #   continue
      
        # if done == False:
        #   print "Got nothing for:", file
          
  # Stack the results.
  Stack.Scan(path, files, mediaList, subdirs)

if __name__ == '__main__':
  print("Hello, world!")
  path = sys.argv[1]
  files = [os.path.join(path, file) for file in os.listdir(path)]
  media = []
  Scan(path[1:], files, media, [])
  print("Media: ", media)