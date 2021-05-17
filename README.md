# video2pdfslides
# Description
This project converts a video presentation into a deck of pdf slides by capturing screenshots of unique frames

# Setup
pip install -r requirements.txt


# Steps to run the code
python video2pdfslides.py <video_path>

it will capture screenshots of unique frames and save it output folder...once screenshots are captured the program is paused and the user is asked to manually verify the screenshots and delete any duplicate images. Once this is done the program continues and creates a pdf out of the screenshots.

# Example
There are two sample video avilable in "./input", you can test the code using these input by running
<li>python video2pdfslides.py "./input/Test Video 1.mp4" (4 unique slide)
<li>python video2pdfslides.py "./input/Test Video 2.mp4" (19 unique slide)


# More
If you are not happy with the results, you can fine tune parameters given in the code. It is always possible to get good results for any video, if you have right set of parameters. Just play around with it and you will develop an intution.


# Developer contact info
kaushik jeyaraman: kaushikjjj@gmail.com
