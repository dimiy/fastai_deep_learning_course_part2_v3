
#################################################
### THIS FILE WAS AUTOGENERATED! DO NOT EDIT! ###
#################################################
# file to edit: dev_nb/10_augmentation_my_reimplementation.ipynb

from exports.nb_09 import *


# Ensure that images are first converted to RGB format.
# Uses the RGB transform we created in notebook 08.
MakeRGB()._order = 0

imagenette_url = 'https://s3.amazonaws.com/fast-ai-imageclas/imagenette'

import random

def show_image(im, ax=None, figsize=(3,3)):
    if ax is None: _, ax = plt.subplots(1, 1, figsize=figsize)
    ax.axis('off')
    # Place channels in tensor's final dimension, if necessary,
    # so that image can be displayed by matplotlib.
    if im.size(-1) not in [3,4]: im = im.permute(1, 2, 0)
    ax.imshow(im)

def show_batch(x, cols=4, rows=None, figsize=None):
    # Put on CPU so that we can plot with matplotlib
    if x.device.type == 'cuda': x = x.cpu()
    n = len(x)
    if rows is None: rows = int(math.ceil(n/cols))
    if figsize is None: figsize = (cols*3, rows*3)
    fig, axes = plt.subplots(rows, cols, figsize=figsize)
    for i, ax in zip(x, axes.flat): show_image(i, ax)

class PilTransform(Transform): _order = 11

class PilRandomFlip(PilTransform):
    def __init__(self, p=0.5): self.p=p
    def __call__(self, x):
        return x.transpose(PIL.Image.FLIP_LEFT_RIGHT) if random.random() < self.p else x

class PilRandomDihedral(PilTransform):
    # Defining self.p = p*7/8 is a useful hack to make it easier
    # for any of the 7 possible dihedral transforms to have an
    # equal chance of being chosen, regardless of what value is
    # chosen for p. Multiplying p by 7/8 means we can divude the
    # result into seven different groups, each of the same size.
    def __init__(self, p=0.75): self.p = p*7/8
    def __call__(self, x):
        if random.random() > self.p: return x
        return x.transpose(random.randint(0,6))

from random import randint

# Ensure square-shaped crops are made.
def process_size(size):
    size = listify(size)
    return tuple(size if len(size)==2 else [size[0], size[0]])

def default_crop_size(w,h): return [w,w] if w < h else [h,h]

class GeneralCrop(PilTransform):
    def __init__(self, size, crop_size=None, resample=PIL.Image.NEAREST):
        self.resample, self.size = resample, process_size(size)
        self.crop_size = None if crop_size is None else process_size(crop_size)

    def default_crop_size(self, w, h): return default_crop_size(w,h)

    def __call__(self, x):
        if self.crop_size is None: self.crop_size = self.default_crop_size(*x.size)
        return x.transform(self.size, PIL.Image.EXTENT, self.get_corners(*x.size, *self.crop_size), resample=self.resample)

    def get_corners(self, w, h): return (0,0,w,h)

class CenterCrop(GeneralCrop):
    def __init__(self, size, scale=1.14, resample=PIL.Image.NEAREST):
        super().__init__(size, resample=resample)
        self.scale = scale

    def default_crop_size(self, w, h): return [w/self.scale, h/self.scale]

    def get_corners(self, w, h, wc, hc):
        return ((w-wc)//2, (h-hc)//2, (w-wc)//2+wc, (h-hc)//2+hc)

class RandomResizedCrop(GeneralCrop):
    def __init__(self, size, scale=(0.08, 1.0), ratio=(3./4., 4./3.), resample=PIL.Image.NEAREST):
        super().__init__(size, resample=resample)
        self.scale, self.ratio = scale, ratio

    def get_corners(self, w, h, wc, hc):
        area = w*h

        # Make 10 attempts to randomly select a proper crop from inside the image.
        for attempt in range(10):
            area = random.uniform(*self.scale) * area
            # Generate random number in between 3/4, and 4/3
            ratio = math.exp(random.uniform(math.log(self.ratio[0]), math.log(self.ratio[1])))
            # The following two lines ensure that the ratio of
            # new_w/new_h is between 3/4 and 4/3, and that
            # multiplying new_w by new_h would give us our
            # target area.
            new_w = int(round(math.sqrt(area * ratio)))
            new_h = int(round(math.sqrt(area / ratio)))

            # A crop is proper only if the following condition is true.
            if new_w <= w and new_h <=h:
                # Randomly locate the crop's upper-left corner so that
                # the bottom-right corner is still within the original
                # image's area.
                left = random.randint(0, w - new_w)
                top  = random.randint(0, h - new_h)
                return (left, top, left + new_w, top + new_h)

        # Fall back to using a simple center crop if we can't auto-
        # generate a successful random crop after ten attempts.
        left, top = randint(0, w-self.crop_size[0]), randit(0, h-self.crop_size[1])
        return(left, top, left+self.crop_size[0], top+self.crop_size[1])

from torch import FloatTensor, LongTensor

# Inspired, in part, by mmgp's answer at:
# https://stackoverflow.com/a/14178717
def find_coefficients(source_coords, output_coords,):
    matrix = []
    for p1, p2 in zip(output_coords, source_coords):
        matrix.append([p1[0], p1[1], 1,     0,     0, 0, -p2[0]*p1[0], -p2[0]*p1[1]])
        matrix.append([    0,     0, 0, p1[0], p1[1], 1, -p2[1]*p1[0], -p2[1]*p1[1]])

    # A is a matrix that contains both output plane and source
    # plane coordinates.
    A = FloatTensor(matrix)
    # B is a vector that contains the coordinates located
    # in the source plane (the "world" plane).
    B = FloatTensor(source_coords).view(8,1)

    # The 8 scalars we wish to solve for represent the solution
    # to x in the equation Ax = B. The solution of x, is the
    # transform that will map any point in the input (source)
    # quadrilateral onto a corresponding point in the output plane.
    return list(torch.solve(B, A)[0][:,0])

def warp(image, output_size, source_coords, resample=PIL.Image.NEAREST):
    w,h = output_size
    # Why is the output a rectangle (will always be square in practice)
    # with an upper-left corner at (0,0)? That's cause we need to feed
    # simple square images into our model.
    output_coords = ((0,0), (0,h), (w,h), (w,0))
    coefficients = find_coefficients(source_coords, output_coords)
    return image.transform(output_size, PIL.Image.PERSPECTIVE, coefficients, resample=resample)


# Helper function to generate a random number in between a and b.
def uniform(a,b): return a + (b-a) * random.random()

class PilRandomResizedCropTilt(PilTransform):
    def __init__(self, size, crop_size=None, magnitude=0., resample=PIL.Image.NEAREST):
        self.resample, self.size, self.magnitude = resample, process_size(size), magnitude
        self.crop_size = None if crop_size is None else process_size(crop_size)

    def __call__(self, x):
        if self.crop_size is None: self.crop_size = default_crop_size(*x.size)

        # Randomly choose the coord of the upper-left corner.
        # Choose such that the crop will be entirely inside
        # the bounds of the input image.
        left, top = (randint(0, x.size[0] - self.crop_size[0]),
                     randint(0, x.size[1] - self.crop_size[1]))

        # New in this version: keep magnitude small enough such
        # that all points in the perspective-transformed output
        # will contain points from the crop.
        w_mag_limit = min(self.magnitude, left/self.crop_size[0], (x.size[0]-left)/self.crop_size[0] - 1)
        h_mag_limit = min(self.magnitude, top /self.crop_size[1], (x.size[1]-top) /self.crop_size[1] - 1)

        # Generate random multipliers to scale the width
        # and height of target tilt perspective.
        w_mag = uniform(-w_mag_limit, w_mag_limit)
        h_mag = uniform(-h_mag_limit, h_mag_limit)

        # * Width/height coordinates on upper-left and bottom-right
        #   corners always move same magnitude in same direction.
        #
        # * Same goes for width/height coordinates on upper-right
        #   and bottom-left corners.
        #
        # * However, width/height coordinates on upper-left and
        #   bottom-left corners move same magnitude but in opposite
        #   directions
        #
        # * Same goes for width/height coordinates on upper-right and
        #   bottom-right corners.
        #
        # The above guidelines prevent image from being squished when
        # a perspective transform is applied.
        #
        # To understand the matrix below, imagine we begin with a square
        # at coordinates ((0,0), (0,1), (1,1), (0,1)), and then shift
        # the width coordinates by w_mag and the height coordinates by
        # h_mag. In order to stay true to the guidelines listed in the
        # bullets above, the corner coordinates would have to be
        # modified in the following manner:
        source_corners = tensor([[ -w_mag,  -h_mag],
                                 [  w_mag, 1+h_mag],
                                 [1-w_mag, 1-h_mag],
                                 [1+w_mag,   h_mag]])

        # The above matrix represents a sort of "unit square" version of
        # the randomly generated source quadrilateral. Now we just
        # scale (enlarge) it so that its area is the same as that of
        # or desired crop size, and we locate its position (relative
        # to the original image) using the upper-left corner coordinates
        # that were randomly generated:
        source_corners = source_corners * tensor(self.crop_size).float() + tensor([left,top]).float()

        # Format the four corner coordinates into a tuple.
        source_corners = tuple([(int(o[0].item()), int(o[1].item())) for o in source_corners])

        # Now that we have our randomly generated source quadrilateral,
        # we can solve for, and then execute, the transform that maps
        # its points to points in the square image we desire as our
        # output.
        return warp(x, self.size, source_corners, resample=self.resample)