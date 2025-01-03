import os
import io
import json
import sys
import subprocess
from PIL import Image, ImageFilter

import torch
import torch.nn as nn
#import torch.nn.functional as F
import torchvision
from torchvision import models, datasets, transforms


try:
    import boto3
except Exception as e:
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'boto3'])
    print('Installed boto3')
    import boto3

device_type = "cuda:0" if torch.cuda.is_available() else "cpu"
print(f"Device type is '{device_type}'")
device = torch.device(device_type)


def net():
    '''
    TODO: Complete this function that initializes your model
          Remember to use a pretrained model
    '''
    # we will start with a simpler 18-layer network
    #model = models.resnet18(weights='IMAGENET1K_V1')
    #model = models.resnet18(pretrained=True)
    # 18 does not perform well, let's try 34
    model = models.resnet34(pretrained=True)

    # we will start with the fixed feature extractor scenario, which replaces the last FC layer with a new
    # one with random weights, and only train that layer, this will take shorter time to train
    for param in model.parameters():
        param.requires_grad = False

    in_feature_count = model.fc.in_features
    model.fc = nn.Linear(in_feature_count, 5)

    model = model.to(device)

    print('Created a model fined tuned from RESNET34')

    return model


def model_fn(model_dir):
    model = net()

    with open(os.path.join(model_dir, "model.pt"), "rb") as model_file:
        checkpoint = torch.load(model_file, map_location = device)
        model.load_state_dict(checkpoint)
        print('Loaded model params from checkpoint')

    return model


# we override this because the default only supports JSON, CSV, NPZ request content types
def input_fn(request_body, content_type):
    if content_type == 'image/jpeg':
        print('Got JPEG input')

        return Image.open(io.BytesIO(request_body))

    if content_type == 'application/json':
        print('Got JSON input: ')
        print(request_body)

        inputs = json.loads(request_body)
        is_enhanced = inputs.get('is_enhanced', 1)
        s3_uri = inputs.get('s3_uri')
        if s3_uri is None:
            raise Exception("inference JSON request is missing the 's3_uri' parameter")
        array = s3_uri.split('/')
        bucket = array[2]
        prefix = '/'.join(array[3:])
        print(f"DEBUG: bucket '{bucket}', prefix '{prefix}'")

        s3_client = boto3.client('s3')

        local_file = 'image.jpg'
        s3_client.download_file(bucket, prefix, local_file)
        print(f"Downloaded '{s3_uri}' from S3")

        enhanced_image = image = Image.open(local_file)
        width, height = image.size
        print(f'Opened the image ({width} x {height} pixels)')

        if is_enhanced == 0:
            # need to enhance it
            enhanced_image = image.filter(ImageFilter.UnsharpMask(radius=4, percent=150, threshold=3))
            print('Enhanced the downloaded image')

        return enhanced_image

    raise Exception(f"inference request content type '{content_type}' not supported")


# we override this to apply transforms
def predict_fn(data, model):
    prediction = None

    try:
        val_transforms = transforms.Compose([
            transforms.Resize(256),
            transforms.CenterCrop(224),
            transforms.ToTensor(),
            transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
        ])

        transformed_data = val_transforms(data)

        # also need to add a dimension
        transformed_data = transformed_data.unsqueeze(0)

        print('Transformed input data')

        # set model to evaluation mode
        model.eval()

        with torch.no_grad():
            transformed_data = transformed_data.to(device)
            print('About to ask model to make prediction')
            prediction = model(transformed_data)
            print('Got prediction')
            print(prediction)

    except Exception as e:
        print(f"Got an exception at predict_fn(): '{e}'")

    return prediction