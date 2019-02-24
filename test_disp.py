import torch
import torchvision.transforms
from scipy.misc import imresize
from scipy.ndimage.interpolation import zoom
import numpy as np
from path import Path
import argparse
from tqdm import tqdm
import pdb
from models import DispNetS, Disp_res, Disp_vgg, Disp_vgg_feature, Disp_vgg_BN, FCRN, deeplab_depth, PoseExpNet
# for depth ground truth
from imageio import imsave
from utils import tensor2array

parser = argparse.ArgumentParser(description='Script for DispNet testing with corresponding groundTruth',
                                 formatter_class=argparse.ArgumentDefaultsHelpFormatter)
parser.add_argument("--network", required=True, type=str, help="network type")
parser.add_argument('--imagenet-normalization', action='store_true', help='use imagenet parameter for normalization.')

parser.add_argument("--pretrained-dispnet", required=True, type=str, help="pretrained DispNet path")
parser.add_argument("--pretrained-posenet", default=None, type=str, help="pretrained PoseNet path (for scale factor)")
parser.add_argument("--img-height", default=128, type=int, help="Image height")
parser.add_argument("--img-width", default=416, type=int, help="Image width")
parser.add_argument("--no-resize", action='store_true', help="no resizing is done")
parser.add_argument("--min-depth", default=1e-3)
parser.add_argument("--max-depth", default=80)

parser.add_argument("--dataset-dir", default='.', type=str, help="Dataset directory")
parser.add_argument("--dataset-list", default=None, type=str, help="Dataset list file")
parser.add_argument("--output-dir", default=None, type=str, help="Output directory for saving predictions in a big 3D numpy file")

parser.add_argument("--gt-type", default='KITTI', type=str, help="GroundTruth data type", choices=['npy', 'png', 'KITTI', 'stillbox'])
parser.add_argument("--img-exts", default=['png', 'jpg', 'bmp'], nargs='*', type=str, help="images extensions to glob")

device = torch.device("cuda") if torch.cuda.is_available() else torch.device("cpu")


@torch.no_grad()
def main():
    args = parser.parse_args()
    if args.gt_type == 'KITTI':
        from kitti_eval.depth_evaluation_utils import test_framework_KITTI as test_framework
    elif args.gt_type == 'stillbox':
        from stillbox_eval.depth_evaluation_utils import test_framework_stillbox as test_framework

    #choose corresponding net type
    if args.network=='dispnet':
    	disp_net = DispNetS().to(device)
    elif args.network=='disp_res':
    	disp_net = Disp_res().to(device)
    elif args.network=='disp_vgg':
    	disp_net = Disp_vgg_feature().to(device)
    elif args.network=='disp_vgg_BN':
        disp_net = Disp_vgg_BN().to(device)
    elif args.network=='FCRN':
        disp_net = FCRN().to(device)
    elif args.network=='ASPP':
        disp_net = deeplab_depth().to(device)  
    else:
    	raise "undefined network"

    weights = torch.load(args.pretrained_dispnet)
    disp_net.load_state_dict(weights['state_dict'])
    disp_net.eval()

    if args.pretrained_posenet is None:
        print('no PoseNet specified, scale_factor will be determined by median ratio, which is kiiinda cheating\
            (but consistent with original paper)')
        seq_length = 0
    else:
        weights = torch.load(args.pretrained_posenet)
        seq_length = int(weights['state_dict']['conv1.0.weight'].size(1)/3)
        pose_net = PoseExpNet(nb_ref_imgs=seq_length - 1, output_exp=False).to(device)
        pose_net.load_state_dict(weights['state_dict'], strict=False)

    dataset_dir = Path(args.dataset_dir)
    if args.dataset_list is not None:
        with open(args.dataset_list, 'r') as f:
            test_files = list(f.read().splitlines())
    else:
        test_files = [file.relpathto(dataset_dir) for file in sum([dataset_dir.files('*.{}'.format(ext)) for ext in args.img_exts], [])]

    framework = test_framework(dataset_dir, test_files, seq_length, args.min_depth, args.max_depth)

    print('{} files to test'.format(len(test_files)))
    errors = np.zeros((2, 7, len(test_files)), np.float32)
    if args.output_dir is not None:
        output_dir = Path(args.output_dir)
        output_dir.makedirs_p()

    for j, sample in enumerate(tqdm(framework)):
        tgt_img = sample['tgt']

        ref_imgs = sample['ref']

        h,w,_ = tgt_img.shape
        if (not args.no_resize) and (h != args.img_height or w != args.img_width):
            tgt_img = imresize(tgt_img, (args.img_height, args.img_width)).astype(np.float32)
            ref_imgs = [imresize(img, (args.img_height, args.img_width)).astype(np.float32) for img in ref_imgs]

        tgt_img = np.transpose(tgt_img, (2, 0, 1))
        ref_imgs = [np.transpose(img, (2,0,1)) for img in ref_imgs]

        tgt_img = torch.from_numpy(tgt_img)#.unsqueeze(0)
       
        #for different normalize method
        if args.imagenet_normalization:
        	normalize = torchvision.transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
        else:
        	normalize = torchvision.transforms.Normalize(mean=[0.5, 0.5, 0.5], std=[0.5, 0.5, 0.5])
        tgt_img = normalize(tgt_img/255).unsqueeze(0).to(device)

        for i, img in enumerate(ref_imgs):
            img = torch.from_numpy(img).unsqueeze(0)
            img = ((img/255 - 0.5)/0.5).to(device)
            ref_imgs[i] = img

        pred_disp = disp_net(tgt_img).cpu().numpy()[0,0]

        if args.output_dir is not None:
            if j == 0:
                predictions = np.zeros((len(test_files), *pred_disp.shape))
            predictions[j] = 1/pred_disp

        gt_depth = sample['gt_depth']

        pred_depth = 1/pred_disp
        use_zoom=True#option for zoom
        
        if use_zoom:
            pred_depth_zoomed = zoom(pred_depth,
                                     (gt_depth.shape[0]/pred_depth.shape[0],
                                      gt_depth.shape[1]/pred_depth.shape[1])
                                     ).clip(args.min_depth, args.max_depth)
        else:# did not perform well
            depth_scale = np.amax(pred_depth)
            pred_depth_zoomed = (imresize(pred_depth,
                                          (gt_depth.shape[0],
                                           gt_depth.shape[1])
                                          )/255.0*depth_scale).clip(args.min_depth, args.max_depth)

        #ground truth depth production
        tensor_depth = torch.from_numpy(gt_depth).to(device)
        #tensor_depth = tensor_depth.unsqueeze(1)
        tensor_depth[tensor_depth == 0] = 1000
        disp_to_show = (1/tensor_depth).clamp(0,10)#;pdb.set_trace()
        #print(disp_to_show.size())
        #disp_to_show = np.clip(1/tensor_depth, 0, 10)
        disp = (255*tensor2array(disp_to_show, max_value=None, colormap='bone',channel_first=False)).astype(np.uint8)
        imsave(Path('groundtruth')/'{}_disp.png'.format(j), disp)

        if sample['mask'] is not None:
            pred_depth_zoomed = pred_depth_zoomed[sample['mask']]
            gt_depth = gt_depth[sample['mask']]

        if seq_length > 0:
            # Reorganize ref_imgs : tgt is middle frame but not necessarily the one used in DispNetS
            # (in case sample to test was in end or beginning of the image sequence)
            middle_index = seq_length//2
            tgt = ref_imgs[middle_index]
            reorganized_refs = ref_imgs[:middle_index] + ref_imgs[middle_index + 1:]
            _, poses = pose_net(tgt, reorganized_refs)
            mean_displacement_magnitude = poses[0,:,:3].norm(2,1).mean().item()

            scale_factor = sample['displacement'] / mean_displacement_magnitude
            errors[0,:,j] = compute_errors(gt_depth, pred_depth_zoomed*scale_factor)

       # scale_factor = np.median(gt_depth)/np.median(pred_depth_zoomed)
        scale_factor=1
        errors[1,:,j] = compute_errors(gt_depth, pred_depth_zoomed*scale_factor)

        # #ground truth depth production
        # tensor_depth = torch.from_numpy(gt_depth).to(device)
        # tensor_depth = tensor_depth.unsqueeze(1)
        # tensor_depth[tensor_depth == 0] = 1000
        # disp_to_show = (1/tensor_depth).clamp(0,10);pdb.set_trace()
        # #print(disp_to_show.size())
        # #disp_to_show = np.clip(1/tensor_depth, 0, 10)
        # disp = (255*tensor2array(disp_to_show, max_value=None, colormap='bone',channel_first=False)).astype(np.uint8)
        # imsave(Path('groundtruth')/'{}_disp.png'.format(j), disp)

    mean_errors = errors.mean(2)
    error_names = ['abs_rel','sq_rel','rms','log_rms','a1','a2','a3']
    if args.pretrained_posenet:
        print("Results with scale factor determined by PoseNet : ")
        print("{:>10}, {:>10}, {:>10}, {:>10}, {:>10}, {:>10}, {:>10}".format(*error_names))
        print("{:10.4f}, {:10.4f}, {:10.4f}, {:10.4f}, {:10.4f}, {:10.4f}, {:10.4f}".format(*mean_errors[0]))

    print("Results with scale factor determined by GT/prediction ratio (like the original paper) : ")
    print("{:>10}, {:>10}, {:>10}, {:>10}, {:>10}, {:>10}, {:>10}".format(*error_names))
    print("{:10.4f}, {:10.4f}, {:10.4f}, {:10.4f}, {:10.4f}, {:10.4f}, {:10.4f}".format(*mean_errors[1]))

    if args.output_dir is not None:
        np.save(output_dir/'predictions.npy', predictions)


#interpolate ground truth map
def lin_interp(shape, xyd):
    # taken from https://github.com/hunse/kitti
    m, n = shape
    ij, d = xyd[:, 1::-1], xyd[:, 2]
    f = LinearNDInterpolator(ij, d, fill_value=0)
    J, I = np.meshgrid(np.arange(n), np.arange(m))
    IJ = np.vstack([I.flatten(), J.flatten()]).T
    disparity = f(IJ).reshape(shape)
    return disparity

def compute_errors(gt, pred):
    thresh = np.maximum((gt / pred), (pred / gt))
    a1 = (thresh < 1.25   ).mean()
    a2 = (thresh < 1.25 ** 2).mean()
    a3 = (thresh < 1.25 ** 3).mean()

    rmse = (gt - pred) ** 2
    rmse = np.sqrt(rmse.mean())

    rmse_log = (np.log(gt) - np.log(pred)) ** 2
    rmse_log = np.sqrt(rmse_log.mean())

    abs_rel = np.mean(np.abs(gt - pred) / gt)

    sq_rel = np.mean(((gt - pred)**2) / gt)

    return abs_rel, sq_rel, rmse, rmse_log, a1, a2, a3


if __name__ == '__main__':
    main()
