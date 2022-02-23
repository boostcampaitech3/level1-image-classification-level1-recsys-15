import os
import pandas as pd
from PIL import Image

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader

from torchvision import transforms
from torchvision.transforms import Resize, ToTensor, Normalize


from torch.utils.data import Dataset, Subset, random_split


from pandas import DataFrame
import torch.optim as optim
import torchvision.models as models
import math
import argparse
import numpy as np
from torch.utils.tensorboard import SummaryWriter
# 테스트 데이터셋 폴더 경로를 지정해주세요.
train_dir = '/opt/ml/input/data/train'
test_dir = '/opt/ml/input/data/eval'


class MyModel(nn.Module):
    def __init__(self, num_classes: int = 1000):
        super(MyModel, self).__init__()
        self.model = models.resnet152()
        self.model.conv1 = nn.Conv2d(3, 64, kernel_size=(7,7), stride=(2, 2), padding=(3, 3), bias=False)
        self.model.fc = torch.nn.Linear(in_features=2048, out_features=18, bias=True)
        torch.nn.init.xavier_uniform_(self.model.fc.weight)
        stdv = 1. / math.sqrt(self.model.fc.weight.size(1))
        self.model.fc.bias.data.uniform_(-stdv,stdv)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.model(x)
        return x


from glob import glob
class TrainDataset(Dataset):    #Dataset만 받아야 한다.
    def __init__(self, transform='', val_ratio=0.2):
        self.transform = transform
        self.X = glob('/opt/ml/input/data/train/images/*/*')
        self.Y = []
        self.val_ratio = val_ratio
        
        for i,img_dir in enumerate(self.X):
            tmp = img_dir.split("/")
            mask,gender_age = tmp[-1],tmp[-2].split("_")
            gender,age = gender_age[1],int(gender_age[-1])

            if 30<=age<60:
                age = 1
            elif age>=60:
                age = 2
            else:
                age = 0

            if gender[0]=='F':
                gender = 1
            else:
                gender = 2

            if 'incorrect' in tmp:
                mask = 1
            elif 'normal' in tmp:
                mask = 2
            else:
                mask = 0
            
            self.Y.append(6*mask+3*gender+age)


    def __getitem__(self, index):
        image = Image.open(self.X[index])

        if self.transform:
            image = self.transform(image)
        return image, self.Y[index]

    def __len__(self):
        return len(self.X)

    def split_dataset(self):
        """
        데이터셋을 train 과 val 로 나눕니다,
        pytorch 내부의 torch.utils.data.random_split 함수를 사용하여
        torch.utils.data.Subset 클래스 둘로 나눕니다.
        구현이 어렵지 않으니 구글링 혹은 IDE (e.g. pycharm) 의 navigation 기능을 통해 코드를 한 번 읽어보는 것을 추천드립니다^^
        """
        n_val = int(len(self) * self.val_ratio)
        n_train = len(self) - n_val
        train_set, val_set = random_split(self, [n_train, n_val])
        return train_set, val_set


class TestDataset(Dataset):
    def __init__(self, img_paths, transform):
        self.img_paths = img_paths
        self.transform = transform

    def __getitem__(self, index):
        image = Image.open(self.img_paths[index])

        if self.transform:
            image = self.transform(image)
        return image

    def __len__(self):
        return len(self.img_paths)

transform = transforms.Compose([
    Resize((512, 384), Image.BILINEAR),
    ToTensor(),
    Normalize(mean=(0.5, 0.5, 0.5), std=(0.2, 0.2, 0.2)),
])

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--seed', type=int, default=42, help='random seed (default: 42)')
    parser.add_argument('--epochs', type=int, default=1, help='number of epochs to train (default: 1)')
    parser.add_argument('--dataset', type=str, default='MaskBaseDataset', help='dataset augmentation type (default: MaskBaseDataset)')
    parser.add_argument('--augmentation', type=str, default='BaseAugmentation', help='data augmentation type (default: BaseAugmentation)')
    parser.add_argument("--resize", nargs="+", type=list, default=[128, 96], help='resize size for image when training')
    parser.add_argument('--batch_size', type=int, default=20, help='input batch size for training (default: 20)')
    parser.add_argument('--valid_batch_size', type=int, default=1000, help='input batch size for validing (default: 1000)')
    parser.add_argument('--model', type=str, default='BaseModel', help='model type (default: BaseModel)')
    parser.add_argument('--optimizer', type=str, default='SGD', help='optimizer type (default: SGD)')
    parser.add_argument('--lr', type=float, default=1e-3, help='learning rate (default: 1e-3)')
    parser.add_argument('--val_ratio', type=float, default=0.2, help='ratio for validaton (default: 0.2)')
    parser.add_argument('--criterion', type=str, default='cross_entropy', help='criterion type (default: cross_entropy)')
    parser.add_argument('--lr_decay_step', type=int, default=20, help='learning rate scheduler deacy step (default: 20)')
    parser.add_argument('--log_interval', type=int, default=20, help='how many batches to wait before logging training status')
    parser.add_argument('--name', default='exp', help='model save at {SM_MODEL_DIR}/{name}')
    parser.add_argument('--model_dir', type=str, default=os.environ.get('SM_MODEL_DIR', './model'))
    args = parser.parse_args()
    save_dir = os.path.join(args.model_dir, args.name)


    logger = SummaryWriter(log_dir=os.path.join(save_dir, args.name))

    train_data, val_set = TrainDataset(transform=transform).split_dataset()
    # x_data = TrainDataset()


    train_loader = DataLoader(train_data, shuffle=True,batch_size=args.batch_size)

    val_loader = DataLoader(train_data, shuffle=True,batch_size=args.batch_size)

    use_cuda = torch.cuda.is_available()
    device = torch.device("cuda" if use_cuda else "cpu")

    model = MyModel().to(device)

    loss_fn = torch.nn.CrossEntropyLoss()
    optm = optim.Adam(model.parameters(), lr=1e-3)

    best_val_acc = 0
    best_val_loss = np.inf
    for epoch in range(args.epochs):
        loss_value = 0
        matches = 0
        model.train()
        for i,(input, label) in enumerate(train_loader):
            input = input.to(device)
            label = label.to(device)
            optm.zero_grad()
            output = model(input)      
            _,preds = torch.max(output,1)

            loss = loss_fn(output, label)
            loss.backward()
            optm.step()
            
            loss_value += loss.item()
            matches += (preds == label).sum().item()
            if (i + 1) % args.log_interval == 0:
                train_loss = loss_value / args.log_interval
                train_acc = matches / args.batch_size / args.log_interval
                current_lr = args.lr
                print(
                    f"Epoch[{epoch}/{args.epochs}]({i + 1}/{len(train_loader)}) || "
                    f"training loss {train_loss:4.4} || training accuracy {train_acc:4.2%} || lr {current_lr}"
                )

                loss_value = 0
                matches = 0





        with torch.no_grad():
            print("Calculating validation results...")
            model.eval()
            val_loss_items = []
            val_acc_items = []
            for val_batch in val_loader:
                inputs, labels = val_batch
                inputs = inputs.to(device)
                labels = labels.to(device)

                outs = model(inputs)
                preds = torch.argmax(outs, dim=-1)

                loss_item = loss_fn(outs, labels).item()
                acc_item = (labels == preds).sum().item()
                val_loss_items.append(loss_item)
                val_acc_items.append(acc_item)


            val_loss = np.sum(val_loss_items) / len(val_loader)
            val_acc = np.sum(val_acc_items) / len(val_set)
            best_val_loss = min(best_val_loss, val_loss)
            if val_acc > best_val_acc:
                print(f"New best model for val accuracy : {val_acc:4.2%}! saving the best model..")
                torch.save(model.state_dict(), f"{save_dir}/best.pth")
                best_val_acc = val_acc
            torch.save(model.state_dict(), f"{save_dir}/last.pth")
            print(
                f"[Val] acc : {val_acc:4.2%}, loss: {val_loss:4.2} || "
                f"best acc : {best_val_acc:4.2%}, best loss: {best_val_loss:4.2}"
            )
            logger.add_scalar("Val/loss", val_loss, epoch)
            logger.add_scalar("Val/accuracy", val_acc, epoch)
            
            
            