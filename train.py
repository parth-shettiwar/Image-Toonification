import torch
import torch.nn as nn
from torch.optim import AdamW

from utils.helpers import unnormalize
import torchvision.utils as vutils
from utils.loss import ContentLoss, AdversialLoss
from utils.transforms import get_pair_transforms
from utils.datasets import get_dataloader
from models.discriminator import Discriminator
from models.generator import Generator


def train():
    torch.manual_seed(1337)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    # Config
    batch_size = 16
    image_size = 256
    learning_rate = 1e-4
    beta1, beta2 = (.5, .99)
    weight_decay = 1e-4
    epochs = 100

    # Models
    netD = Discriminator().to(device)
    netG = Generator().to(device)
    # Here you should load the pretrained G
    netG.load_state_dict(torch.load("./checkpoints/pretrained_netGF.pth"))
    # netD.load_state_dict(torch.load("./checkpoints/trained_netD.pth"))
    optimizerD = AdamW(netD.parameters(), lr=learning_rate, betas=(beta1, beta2), weight_decay=weight_decay)
    optimizerG = AdamW(netG.parameters(), lr=learning_rate, betas=(beta1, beta2), weight_decay=weight_decay)

    scaler = torch.cuda.amp.GradScaler()

    # Labels
    cartoon_labels = torch.ones (batch_size, 1, image_size // 4, image_size // 4).to(device)
    fake_labels    = torch.zeros(batch_size, 1, image_size // 4, image_size // 4).to(device)

    # Loss functions
    content_loss = ContentLoss().to(device)
    adv_loss     = AdversialLoss(cartoon_labels, fake_labels).to(device)
    BCE_loss     = nn.BCEWithLogitsLoss().to(device)

    # Dataloaders
    real_dataloader    = get_dataloader("./datasets/flickr6k_images/",           size = image_size, bs = batch_size)
    cartoon_dataloader = get_dataloader("./datasets/carton_data/",   size = image_size, bs = batch_size, trfs=get_pair_transforms(image_size))

    # --------------------------------------------------------------------------------------------- #
    # Training Loop

    # Lists to keep track of progress
    img_list = []
    G_losses = []
    D_losses = []
    iters = 0

    tracked_images = next(iter(real_dataloader)).to(device)

    print("Starting Training Loop...")
    # For each epoch.
    for epoch in range(epochs):
        print("training epoch ", epoch)
        # For each batch in the dataloader.
        for i, (cartoon_edge_data, real_data) in enumerate(zip(cartoon_dataloader, real_dataloader)):

            ############################
            # (1) Update D network: maximize log(D(x)) + log(1 - D(G(z)))
            ###########################
            
            # Reset Discriminator gradient.
            netD.zero_grad()

            # Format batch.
            cartoon_data   = cartoon_edge_data[:, :, :, :image_size].to(device)
            edge_data      = cartoon_edge_data[:, :, :, image_size:].to(device)
            real_data      = real_data.to(device)

            with torch.cuda.amp.autocast():
                # Generate image
                generated_data = netG(real_data)

                # Forward pass all batches through D.
                cartoon_pred   = netD(cartoon_data)      #.view(-1)
                edge_pred      = netD(edge_data)         #.view(-1)
                generated_pred = netD(generated_data)    #.view(-1)

                # Calculate discriminator loss on all batches.
                errD = adv_loss(cartoon_pred, generated_pred, edge_pred)
            
            # Calculate gradients for D in backward pass
            scaler.scale(errD).backward(retain_graph=True)
            D_x = cartoon_pred.mean().item() # Should be close to 1

            # Update D
            scaler.step(optimizerD)


            ############################
            # (2) Update G network: maximize log(D(G(z)))
            ###########################
            
            # Reset Generator gradient.
            netG.zero_grad()
            
            with torch.cuda.amp.autocast():
                # Since we just updated D, perform another forward pass of all-fake batch through D
                generated_pred = netD(generated_data) #.view(-1)

                # Calculate G's loss based on this output
                errG = BCE_loss(generated_pred, cartoon_labels) + content_loss(generated_data, real_data)

            # Calculate gradients for G
            scaler.scale(errG).backward()

            D_G_z2 = generated_pred.mean().item() # Should be close to 1
            
            # Update G
            scaler.step(optimizerG)

            scaler.update()
            
            # ---------------------------------------------------------------------------------------- #

            # Save Losses for plotting later
            G_losses.append(errG.item())
            D_losses.append(errD.item())
            if i % 125 == 0:
                print('[%d/%d][%d/%d]\tLoss_D: %.4f\t Loss_G: %.4f\tD(x): %.4f\tD(G(z)): %.4f'
                    % (epoch, epochs, i, len(real_dataloader),
                        errD.item(), errG.item(), D_x, D_G_z2))
                # predict_file('./datasets/real/490870.jpg', './datasets/out2.jpg')
            # Check how the generator is doing by saving G's output on tracked_images
            if iters % 200 == 0:        
                with torch.no_grad():
                    fake = netG(tracked_images)
                vutils.save_image(unnormalize(fake), f"images/{epoch}_{i}.png", padding=2)

            if iters % 1000 == 0:
                torch.save(netG.state_dict(), f"checkpoints_new/netG_e{epoch}_i{iters}_l{errG.item()}.pth")
                torch.save(netD.state_dict(), f"checkpoints_new/netD_e{epoch}_i{iters}_l{errG.item()}.pth")

            iters += 1



if __name__ == "__main__":
    train()
