import epitran  # needs to be installed
import regex    # needs to be installed
import sys
import timeit
import gzip as gz

from functools import partial, lru_cache
from itertools import islice
from multiprocessing import Pool

ENGLISH = "abcdefghijklmnopqrstuvwxyz"
ENGLISH = ENGLISH + ENGLISH.upper()

POLISH = "aąbcćdeęfghijklłmnńoóprsśtuwyzźżqvx"
POLISH = POLISH + POLISH.upper()

epi_en = epitran.Epitran('eng-Latn')  # For English scripts (REQUIRES INSTALLING FLITE!)
epi_pol = epitran.Epitran('pol-Latn')  # For Polish scripts  

######################################################################
# Function that transform strings (words or sentences) into ipa tokens
######################################################################

### English version
def english_to_ipa(sequence):

    """Transcribe a string in English to ipa.

    Parameters
    ----------
    sequence : str
        Text to transcribe to ipa

    Returns
    -------
    str
        Transcribed text in ipa

    Notes
    -----
    'ɹ̩' is transformed into 'əɹ'
    as Epitran transforms any 'ə' (short or long) followed by r into 'ɹ̩'
    """

    string_ipa = epi_en.transliterate(sequence).replace('ɹ̩', 'əɹ')
    return string_ipa

### Polish version
def polish_to_ipa(sequence):

    """Transcribe a string in Polish to ipa.

    Parameters
    ----------
    sequence : str
        Text to transcribe to ipa

    Returns
    -------
    str
        Transcribed text in ipa
    """

    string_ipa = epi_pol.transliterate(sequence)
    return string_ipa

##################################
# Function that syllabifies a word
##################################

### First we create a function that matches the syllable pattern in a word
### We will run it once and feed the compiled regular expression function
### to the different syllabifiers. This to avoid re-running it multiple times 
### inside the syllabifiers 

# English version
def regex_en_ipa():

    """Returns compiled regular expression that matches
    overlapping syllables in English words transcribed to IPA
    """

    vowels = 'æɑəɛiɪɔuʊʌ'
    diphtongues = "|".join(('aj', 'aw', 'ej', 'oj', 'ow'))
    consonants = 'θwlmvhpɡŋszbkʃɹdnʒjtðf͡' 

    # syllable starts after beginning of word or previous vowel/diphtongue
    # consists of a vowel/diphtongue preceded/followed by 0 or more consonsants
    # ends before next vowel/diphtongue or end of word
    pattern_syllable = f"""(?=  # ? Look ahead to make sure to match a substring without removing it for later checkes
                            (?<=[{vowels}]|{diphtongues}|^) # ? to not return the result yet | <: says look behind 
                            ([{consonants}]* (?:[{vowels}]|{diphtongues}) [{consonants}]*)
                            (?:[{vowels}]|{diphtongues}|$))
                        """
    # add pattern to match words made of only consonants
    pattern_consonant = f"""(?<=^)(?:[{consonants}])+(?:$)"""

    syllables = regex.compile(pattern_syllable, regex.VERBOSE)
    consonants = regex.compile(pattern_consonant, regex.VERBOSE)

    return syllables, consonants

# Polish version 
def regex_pol_ipa():

    """Returns compiled regular expression that matches
    overlapping syllables in English words transcribed to IPA
    """
    
    vowels = 'aɛiɨɔu' 
    special_vowels = "|".join(('ɛ̃','ɔ̃'))
    consonants = 'ɕʑʐɣɲʂxwlmvpɡŋszbkdrnjtf' ## To CHECK
    special_consonants = "|".join(('d͡z', 'd͡ʑ', 'd͡ʐ', 't͡ɕ', 't͡s', 't͡ʂ', 'ɡʲ', 'kʲ')) # needs to copy 'xʲ' and 'j̃' from real examples when I encounter them

    # syllable starts after beginning of word or previous vowel
    # consists of a vowel preceded/followed by 0 or more consonsants
    # ends before next vowel/diphtongue or end of word
    pattern_syllable = f"""(?=  # ? Look ahead to make sure to match a substring without removing it for later checkes
                           (?<=[{vowels}]|{special_vowels}|^) # ? to not return the result yet | <: says look behind 
                           ([{consonants}|{special_consonants}]* (?:[{vowels}]|{special_vowels}) [{consonants}|{special_consonants}]*)
                           (?:[{vowels}]|{special_vowels}|$)
                           ) 
                        """

    # add pattern to match words made of only consonants
    pattern_consonant = f"""(?<=^)(?:[{consonants}|{special_consonants}])+(?:$)"""

    syllables = regex.compile(pattern_syllable, regex.VERBOSE)
    consonants = regex.compile(pattern_consonant, regex.VERBOSE)

    return syllables, consonants
    
### Main function that syllabies a single word
# Add a cach: allow to cache the results to avoid re-applying the function multiple times when 
# the results have already been generated
@lru_cache(maxsize=None) 
def syllabify(word, ipa_converter, syllable_pattern, add_boundaries=True):

    """Extracts syllables from English word.

    Parameters
    ----------
    word : str
        Word to extract syllables from
    ipa_converter : function
        Function that convert a string to ipa (for Polish, use polish_to_ipa)
    syllable_pattern : tuple 
        Tuple of two regular expressions. The first matches syllables in a word. 
        The second matches words made of only consonants 
    add_boundaries : bool
        hashtags are added as word boundaries to outermost syllables

    Returns
    -------
    str
        Syllables separated by underscores
    """

    # syllable_pattern contains two patterns 
    regular_pattern = syllable_pattern[0] # regular form of a syllable
    consonant_pattern = syllable_pattern[1] # if the word is made of only consonants

    # convert to ipa
    string = ipa_converter(word)

    syllable_matches = regular_pattern.findall(string) 
    if syllable_matches:
        syllables = "_".join(syllable_matches)
    else:
        syllables = "_".join(consonant_pattern.findall(string))

    if add_boundaries:
        syllables = "#" + syllables + "#"
        
    return syllables

##################################
# Function that syllabifies a line
##################################

def tokenize(line):

    """Splits line into lowercase words based on spaces.
    """

    line = line.strip().lower().split(" ")
    return [word for word in line if word]

def syllabify_line(line, 
                   ipa_converter, 
                   syllable_pattern, 
                   not_symbol_pattern, 
                   add_boundaries = True, 
                   as_event = False):

    """Syllabifies words in line.

    Parameters
    ----------
    line : str
        Line to syllabify (typically read from corpus)
    ipa_converter: function
        english_to_ipa or polish_to_ipa
    syllable_pattern : tuple 
        Tuple of two regular expressions. The first matches syllables in a word. 
        The second matches words made of only consonants 
    not_symbol_pattern : compiled regular expression
        Regular expression that matches disallowed characters (e.g. punctuation)
    add_boundaries : bool
        hashtags are added as word boundaries to outermost syllables
    as_event: bool
        If True, result is returned as a (cues, outcomes)-tuple,
        where cues is all syllables and outcomes all words, separated
        by underscores.

    Returns
    -------
    tuple (as_event==True) or list of str
        list of syllables or tuple of syllables and words
    """

    # Clean the line: replaces everything in line matched by symbols_regex with spaces
    line = not_symbol_pattern.sub(" ", line)
    # Divide the line into words 
    words = tokenize(line)

    # Generate the list of syllables
    syllables = []
    for word in words:
        s = syllabify(word = word,
                      ipa_converter = ipa_converter,
                      syllable_pattern = syllable_pattern,
                      add_boundaries = add_boundaries)
        if s != '##':
            syllables.append(s)

    if as_event:
        return "_".join(syllables), "_".join(words)

    return syllables

########################################################
# Function that creates an event file with syllabic cues
########################################################

# First let's create a function that divides a sequence of lines (e.g. a corpus) into 
# chunks that can be later processed in parallel  
def chunk(iterable, chunksize):

    """Returns lazy iterator that yields chunks from iterable.
    """

    iterator = iter(iterable)
    return iter(lambda: list(islice(iterator, chunksize)), [])

# function that creates a generator that syllabifies a sequence of lines 
def syllabify_corpus_generator(lines,
                               ipa_converter,
                               syllable_pattern,
                               not_symbol_pattern,
                               add_boundaries,
                               as_event,
                               numcores,
                               chunksize):

    """Syllabifies lines in parallel.

    Parameters
    ----------
    lines : iterable of str
        Lines to be syllabified, typically an open corpus file
    ipa_converter : function
        Function that convert a string to ipa (for Polish, use polish_to_ipa)
    syllable_pattern : tuple 
        Tuple of two regular expressions. The first matches syllables in a word. 
        The second matches words made of only consonants 
    not_symbol_pattern : compiled regular expression
        Regular expression that matches disallowed characters (e.g. punctuation)
    add_boundaries : bool
        hashtags are added as word boundaries to outermost syllables
    as_event: bool
        If True, results are returned as a (cues, outcomes)-tuple,
        where cues is all syllables and outcomes all words, separated
        by underscores.
    numcores : int
        Number of parallel processes to use (should be <= number of cores)
    chunksize : int
        Number of lines each process will work on in batches
        (Higher values increase memory consumption, but decrease processing
        time, with diminishing returns)   
    """

    # Fills arguments for later use with .imap
    _syllabify = partial(syllabify_line,
                         ipa_converter = ipa_converter,
                         syllable_pattern = syllable_pattern,
                         not_symbol_pattern = not_symbol_pattern,
                         add_boundaries = add_boundaries,
                         as_event = as_event)
    with Pool(numcores) as pool:
        for _chunk in chunk(lines, chunksize * numcores):
            yield from pool.imap(_syllabify, _chunk, # imap gives the results one at a time (# from map)
                                 chunksize = chunksize)

# Main function that syllabify a corpus
def syllabify_corpus(corpus_path,
                     event_file_path,
                     ipa_converter,
                     syllable_pattern,
                     not_symbol_pattern,
                     add_boundaries,
                     numcores,
                     chunksize):

    """Syllabifies a corpus and save the results in a text file.

    Parameters
    ----------
    corpus_path : str
        Path of the corpus to be syllabified
    event_file_path : str
        Path of the event file with syllabic cues
    ipa_converter : function
        Function that convert a string to ipa (for Polish, use polish_to_ipa)
    syllable_pattern : tuple 
        Tuple of two regular expressions. The first matches syllables in a word. 
        The second matches words made of only consonants 
    not_symbol_pattern : compiled regular expression
        Regular expression that matches disallowed characters (e.g. punctuation)
    add_boundaries : bool
        hashtags are added as word boundaries to outermost syllables
    numcores : int
        Number of parallel processes to use (should be <= number of cores)
    chunksize : int
        Number of lines each process will work on in batches
        (Higher values increase memory consumption, but decrease processing
        time, with diminishing returns)   
    """

    with gz.open(event_file_path, "wt", encoding = 'utf-8') as outfile:  
        with open(corpus_path) as corpus:
            start = timeit.time.time()
            results = syllabify_corpus_generator(lines = corpus,
                                                 ipa_converter = ipa_converter,
                                                 syllable_pattern = syllable_pattern,
                                                 not_symbol_pattern = not_symbol_pattern,
                                                 add_boundaries = add_boundaries,
                                                 as_event = True,
                                                 numcores = numcores,
                                                 chunksize = chunksize)
            #list(results)
            for i, syllabified in enumerate(results):

                cues, outcomes = syllabified
                outfile.write(f"{cues}\t{outcomes}\n")   

                if (i % 10000 == 0):
                    took = timeit.time.time() - start
                    took = round(took / 60, 2)
                    sys.stdout.write(f"Processed {i} lines in {took} minutes\r")
                    sys.stdout.flush()
            took = timeit.time.time() - start
            print(f"All processed in {round(took / 60, 2)} minutes!")

def corpus_first_lines(corpus, n):

    """Generate first n lines from corpus.
    """

    for _ in range(n):
        try:
            yield next(corpus)
        except StopIteration:
            return

