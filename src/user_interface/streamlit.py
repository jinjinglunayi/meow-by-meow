import altair as alt
from huggingface_hub import hf_hub_download
import joblib
import numpy as np
import pandas as pd
from pydub import AudioSegment
from pydub.exceptions import CouldntDecodeError
from scipy.interpolate import interp1d
from scipy.io import wavfile
from sklearn.pipeline import Pipeline
import streamlit as st
import sys
from torch import Tensor
import torchaudio

sys.path.append('./meowlib/')
import data_handling

# Set up settings
settings = dict(
    # Analysis parameters
    min_duration_seconds=4.,
    rate=8000,
    behaviors=['uncomfortable', 'hungry', 'comfortable'],

    # Define the model repository and the model filename
    repo_id='zhafen/meow-by-meow-modeling',
    model_filename='k4s0.2r440.pkl',

    # Data parameters
    default_fp='./data/processed_data/combined_meows.mp3',

    # Aesthetic parameters
    color_scheme='tableau10',
)

st.set_page_config(layout="wide")
st.title('Meow-by-Meow')
st.caption(
    'Created by Brady Ali, Jinjing Yi, Tantrik Mukerji, William Craig, '
    'and Zach Hafen-Saavedra '
    'during the Erdos Institute Fall 2023 Program.'
)
st.write(
    "Use machine learning to interpret your cat's "
    "chirps, complaints, yowls, yells, vocalizations, and meows."
)
st.divider()

# Set up the padding, getting the pad size from the number of features
freq_shape = 128
time_shape = 63
pad_transformer = data_handling.PadTransformer()
pad_transformer.max_shape0_ = freq_shape
pad_transformer.max_shape1_ = time_shape

# TODO: Do more preprocessing pre-specgram.
# E.g. cut out leading silence, pad the end, resample.
# The motivation is better consistency for specgrams.

# Preprocessing pipeline
preprocess = Pipeline([
    ('Building a specgram...', data_handling.SpecgramTransformer()),
    # TODO: Rolling Window Parameters are not in physical, intuitive units
    ('Splitting the recording into windows...',
     data_handling.RollingWindowSplitter()),
    ('Padding the data...', pad_transformer),
    ('Flattening the data...', data_handling.FlattenTransformer()),
])

# Read the user-provided .wav file data
st.subheader('Upload a recording of your cat')
user_file = st.file_uploader(
    label=(
        'Accepted formats include .wav, .m4a, and anything accepted by ffmpeg.'
    )
)

# Default case
if user_file is None:
    audio = AudioSegment.from_file(settings['default_fp'])
else:
    try:
        filetype = user_file.type.split('/')[-1]

        # Rename for functionality
        if filetype == 'x-m4a':
            filetype = 'm4a'

        audio = AudioSegment.from_file(user_file, format=filetype)

        if audio.duration_seconds < settings['min_duration_seconds']:
            st.error(
                'Please upload a recording longer than '
                f"{settings['min_duration_seconds']:.2g} seconds."
            )
            assert False
        else:
            st.success('File uploaded!')

    except (AssertionError, CouldntDecodeError, IndexError) as e:
        st.error('Could not load user file. Using default file.')
        audio = AudioSegment.from_file(settings['default_fp'])
        user_file = None

st.divider()

st.subheader('The recording to interpret')

# Upload message
if user_file is None:
    st.write(
        "No recording handy? "
        "We have one ready!"
    )

st.write('Here is the audio we will interpret:')
st.write(audio)

st.divider()

st.subheader('Our analysis')

with st.status('Interpreting...', expanded=True):

    st.write('Retrieving the trained AI model...')
    # Download the model file from the Hugging Face Hub
    model_file = hf_hub_download(
        repo_id=settings['repo_id'],
        filename=settings['model_filename']
    )

    # Load the model using joblib
    model = joblib.load(model_file)

    st.write('Formatting data...')
    # Extract the core data
    sample = np.array(audio.get_array_of_samples())
    sample = sample / np.iinfo(sample.dtype).max

    # Resample to the right rate
    st.write('Resampling to a new frequency...')
    resampler = torchaudio.transforms.Resample(
        audio.frame_rate,
        settings['rate']
    )
    sample = np.array(resampler(Tensor(sample)))
    rate = settings['rate']

    dt = 1. / settings['rate']
    sample_duration = sample.size * dt

    for key, item in preprocess.named_steps.items():
        st.write(key)

    # Preprocess
    X = [(sample, rate)]
    X_transformed = preprocess.fit_transform(X)

    st.write('Employing the model...')

    # Predict
    classifications = model.predict(X_transformed)

st.divider()

st.subheader('Your meow-by-meow interpretation!')

with st.spinner('Visualizing...'):

    # Get the typicall classification
    c_avg = np.argmax(np.bincount(classifications))

    # Format the sample for visualization
    time = np.arange(0., sample_duration, dt)
    sample_df = pd.DataFrame({
        'time': time,
        'sample': sample,
    })

    # Add the classifications
    # TODO: The window centers aren't aligned exactly
    window_centers = np.linspace(
        0,
        sample_duration,
        classifications.size,
    )
    interp_fn = interp1d(window_centers, classifications, kind='nearest')
    sample_df['classification'] = interp_fn(sample_df['time'])
    sample_df['behavior'] = \
        sample_df['classification'].map(pd.Series(settings['behaviors']))

    # Visualize
    # TODO: Represent the fact that we have an averaging window somehow.
    # TODO: Does it really make sense for sentiment to change from one meow
    #       to the next? Probably not, but there can be multiple emotions
    #       so maybe some shine through more-strongly?
    c = alt.Chart(sample_df).mark_line().encode(
        x=alt.X('time', axis=alt.Axis(title='time (seconds)')),
        y=alt.Y(
            'sample',
            axis=alt.Axis(title='amplitude', tickCount=0),
        ),
        # TODO: This creates independent lines. We don't want that.
        color=alt.Color(
            'behavior:N',
        ).scale(scheme=settings['color_scheme']),
    )
    c = c.configure_axisX(
        # Change gridline locations
        values=window_centers,
    )
    c = c.configure_axisY(
        # Remove gridlines
        grid=False
    )
    st.altair_chart(c, use_container_width=True)

    # TODO: An animated video that plays when it records would be neat.
    # TODO: Is "amplitude" intuitive enough for a y-axis label?

    st.markdown(
        (
            "*<p style='text-align: center; font-size: larger'>"
            "*Overall**, your cat sounds "
            f"***{settings['behaviors'][c_avg]}***."
            "</p>"
        ),
        unsafe_allow_html=True,
    )
