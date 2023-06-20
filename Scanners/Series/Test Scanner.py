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
import json
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

import pydoc

# I needed some plex libraries, you may need to adjust your plex install location accordingly
SetupDone              = False
Log                    = None
Handler                = None
TA_CONFIG              = None
PLEX_ROOT              = ""
PLEX_LIBRARY           = {}
PLEX_LIBRARY_URL       = "http://localhost:32400/library/sections/"  # Allow to get the library name to get a log per library https://support.plex.tv/hc/en-us/articles/204059436-Finding-your-account-token-X-Plex-Token

import Media, VideoFiles, Stack, Utils

SSL_CONTEXT            = ssl.SSLContext(SSL_PROTOCOL)
FILTER_CHARS    = "\\/:*?<>|;"  #_.~  
youtube_regexs = [
  '[0-9]{8}_[a-zA-Z0-9]{11}_*.*'    # YYYYMMDD_XXXXXXXXXXX_TITLE.ext
]


def output_help_to_file(filepath="/tmp/test-output.log", request="help"):
    f = open(filepath, 'a')
    out = sys.stdout
    sys.stdout = f
    f.write("\n")
    pydoc.help(request)
    f.write("\n")
    f.close()
    sys.stdout = out
    return

def write_to_test_output(str_out):
  with open("/tmp/test-output.log", 'a') as f:
    f.write("\n" + str_out)

### Setup core variables ################################################################################
def setup():
  global SetupDone
  with open("/tmp/test-output.log","a") as f:
    f.write("\nChecking if SetupDone is set.")
    if SetupDone:
      return
    else:
      SetupDone = True
    

  ### Define PLEX_ROOT ##################################################################################
  global PLEX_ROOT
  PLEX_ROOT = os.path.abspath(os.path.join(os.path.dirname(inspect.getfile(inspect.currentframe())), "..", ".."))
  write_to_test_output("Testing Initial PLEX_ROOT: " + PLEX_ROOT)
  if not os.path.isdir(PLEX_ROOT):
      path_location = { 'Windows': '%LOCALAPPDATA%\\Plex Media Server',
                      'MacOSX':  '$HOME/Library/Application Support/Plex Media Server',
                      'Linux':   '$PLEX_HOME/Library/Application Support/Plex Media Server',
                      'Android': '/storage/emulated/0/Plex Media Server' }
      PLEX_ROOT = os.path.expandvars(path_location[Platform.OS.lower()] if Platform.OS.lower() in path_location else '~')  # Platform.OS:  Windows, MacOSX, or Linux
      write_to_test_output("Platform review required, Platform: " + Platform.OS.lower() + " and the new PLEX_ROOT: " + PLEX_ROOT)

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

def load_ta_config():
  global TA_CONFIG
  if TA_CONFIG: return
  else:
    TA_CONFIG = get_ta_config()
    write_to_test_output("TA_CONFIG: " + str(TA_CONFIG))

def get_ta_config():
  SCANNER_LOCATION = "Scanners/Series/"
  CONFIG_NAME = "config.json"
  write_to_test_output("Expected config.json location: " + os.path.join(PLEX_ROOT, SCANNER_LOCATION, CONFIG_NAME))
  return json.loads(read_file(os.path.join(PLEX_ROOT, SCANNER_LOCATION, CONFIG_NAME)) if os.path.isfile(os.path.join(PLEX_ROOT, SCANNER_LOCATION, CONFIG_NAME)) else "{}")

def test_ta_connection():
  try:
    Log.info("Attempt to connect to TA at {} with provided token.".format(TA_CONFIG['ta_url']))
    ta_ping = json.loads(read_url(Request("{}/api/ping".format(TA_CONFIG['ta_url']), headers={"Authorization": "Token {}".format(TA_CONFIG['ta_token'])})))['response']
    Log.info("Response from TA: {}".format(ta_ping))
    if ta_ping == "pong":
      return True
  except Exception as e: Log.error("Error connecting to TA URL '%s', Exception: '%s'" % (TA_CONFIG['ta_url'], e)); raise e

def get_ta_video_metadata(ytid):
  try:
    Log.info("Attempt to connect to TA at {} with provided token to lookup YouTube ID {}.".format(TA_CONFIG['ta_url'], ytid))
    vid_response = json.loads(read_url(Request("{}/api/video/{}/".format(TA_CONFIG['ta_url'],ytid), headers={"Authorization": "Token {}".format(TA_CONFIG['ta_token'])})))
    Log.info("Response from TA received.")
    if vid_response:
      metadata = {}
      metadata['show'] = "{} [{}]".format(vid_response['data']['channel']['channel_name'], vid_response['data']['channel']['channel_id'])
      metadata['title'] = vid_response['data']['title']
      processed_date = datetime.datetime.strptime(vid_response['data']['published'],"%d %b, %Y")
      metadata['season'] = processed_date.year
      metadata['episode'] = processed_date.strftime("%Y%m%d")
      return metadata
  except Exception as e: Log.error("Error connecting to TA URL '%s', Exception: '%s'" % (TA_CONFIG['ta_url'], e)); raise e

# def get_ta_video_metadata(ytid, iteration = 0, retries = 3):
#   try:
#     if iteration > retries:
#       return None
#     try:
#         full_url = "{}/api/video/{}/".format(TA_CONFIG['ta_url'], ytid)
#         Log.info("Attempt {} to connect to TA at {} with provided token to lookup ID {}.".format(str(iteration + 1), full_url, ytid))
#         metadata = {}
#         r = Request(full_url, headers={"Authorization": "Token {}".format(TA_CONFIG['ta_token'])}))
#         Log.info("Request created")
#         vid_response = json.loads(read_url(r))
#         Log.info("TA responded successfully. Processing response.")
#         metadata['show'] = "{} - {}".format(vid_response['data']['channel']['channel_name'], vid_response['data']['channel']['channel_id'])
#         metadata['title'] = vid_response['data']['title']
#         metadata['season'] = datetime.datetime.strptime(vid_response['data']['published'],"%d %b, %Y").year
#         metadata['episode'] = datetime.datetime.strptime(vid_response['data']['published'],"%d %b, %Y").strftime("%Y%m%d")
#         return metadata
#     except Exception as e: Log.error("Error with getting metadata, waiting 3 seconds and trying again."); time.sleep(3); get_ta_video_metadata(ytid, iteration + 1)
#   except Exception as e: Log.error("Error connecting to TA URL '%s', Exception: '%s'" % (TA_CONFIG['ta_url'], e)); raise e

# Look for episodes.
def Scan(path, files, mediaList, subdirs):
  setup()
  load_ta_config()
  is_ta_on = None
  is_ta_on = test_ta_connection()
  # Scan for video files.
  Log.info("Scanning file paths...")
  VideoFiles.Scan(path, files, mediaList, subdirs)

  # Take top two as show/season, but require at least the top one.
  paths = Utils.SplitPath(path)
  
  if len(paths) > 0 and len(paths[0]) > 0:
    done = False
    Log.info("Starting scan down paths...")
    if done == False:
      (show, year) = VideoFiles.CleanName(paths[0])
      
      for i in files:
        Log.info("Reviewing {}.".format(i))
        done = False
        file = os.path.basename(i)
        (file, ext) = os.path.splitext(file)
        
        # found = False
        for rx in youtube_regexs:
          match = re.search(rx, file, re.IGNORECASE)
          Log.info("Checking if file matches regex `{}`".format(rx))
          if match:
            Log.info("File matches. Gathering filename-based configurations")
            originalAirDate = file[0:7] # YYYYMMDD
            ytid = file[9:20] # XXXXXXXXXXX
            title = file[21:] # Title
            season = originalAirDate[0:4]
            episode = originalAirDate[5:]

            if is_ta_on:
              try:
                Log.info("TA connected previously. Pulling metadata.")
                video_metadata = get_ta_video_metadata(ytid)
                show = video_metadata["show"]
                title = video_metadata["title"]
                season = video_metadata["season"]
                episode = video_metadata["episode"]
              except Exception as e: Log.error("Issue with setting metadata from Video using this metadata: '%s', Exception: '%s'" % (str(video_metadata), e))

            write_to_test_output("Requesting helper with 'Media.Episode'.")
            output_help_to_file(request="Media.Episode")
            tv_show = Media.Episode(show.encode("UTF-8"), season.encode("UTF-8"), None, title.encode("UTF-8"), season.encode("UTF-8"))
            write_to_test_output("Requesting helper with 'tv_show.released_at'.")
            output_help_to_file(request="tv_show.released_at")
            tv_show.released_at = "{}-{}-{}".format(str(episode)[:3],str(episode)[4:5],str(episode)[6:7]).encode("UTF-8")
            tv_show.parts.append(i)
            Log.info("Adding episode to TV show list.")
            write_to_test_output("Requesting helper with 'Media'.")
            output_help_to_file(request="Media")
            write_to_test_output("Requesting helper with 'mediaList'.")
            output_help_to_file(request="mediaList")
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
  print("Test Scanner by lamusmaser for Plex!")
  path = sys.argv[1]
  files = [os.path.join(path, file) for file in os.listdir(path)]
  media = []
  Scan(path[1:], files, media, [])
  print("Files detected: ", media)