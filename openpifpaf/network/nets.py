import torch
import torchvision

from . import basenetworks, heads,heads_corr


class Shell_psf(torch.nn.Module):
    def __init__(self, base_net, head_nets):
        super(Shell_psf, self).__init__()

        self.base_net = base_net
        self.head_nets = torch.nn.ModuleList(head_nets)

    def io_scales(self):
        return [self.base_net.input_output_scale // (2 ** getattr(h, '_quad', 0))
                for h in self.head_nets]

    def forward(self, x):  # pylint: disable=arguments-differ
        x = self.base_net(x)


        results = []
        for hn in self.head_nets:
            results.append(hn(x))

        return results
class Shell(torch.nn.Module):
    def __init__(self, base_net, head_nets):
        super(Shell, self).__init__()

        self.base_net = base_net
        self.head_nets = torch.nn.ModuleList(head_nets)

    def io_scales(self):
        return [self.base_net.input_output_scale // (2 ** getattr(h, '_quad', 0))
                for h in self.head_nets]

    def forward(self, x):  # pylint: disable=arguments-differ
        x = self.base_net(x)

        return [hn(x) for hn in self.head_nets]


class Shell2Stage(torch.nn.Module):
    def __init__(self, base_net, head_nets1, head_nets2):
        super(Shell2Stage, self).__init__()

        self.base_net = base_net
        self.head_nets1 = torch.nn.ModuleList(head_nets1)
        self.head_nets2 = torch.nn.ModuleList(head_nets2)

    @property
    def head_nets(self):
        return list(self.head_nets1) + list(self.head_nets2)

    def io_scales(self):
        return (
            [self.base_net.input_output_scale[0] for _ in self.head_nets1] +
            [self.base_net.input_output_scale[1] for _ in self.head_nets2]
        )

    def forward(self, x):  # pylint: disable=arguments-differ
        x1, x2 = self.base_net(x)
        #print(x1.shape)
        h1 = [hn(x1) for hn in self.head_nets1]
        h2 = [hn(x2) for hn in self.head_nets2]
        return [h for hs in (h1, h2) for h in hs]


class ShellFork(torch.nn.Module):
    def __init__(self, base_net, head_nets1, head_nets2, head_nets3):
        super(ShellFork, self).__init__()

        self.base_net = base_net
        self.head_nets1 = torch.nn.ModuleList(head_nets1)
        self.head_nets2 = torch.nn.ModuleList(head_nets2)
        self.head_nets3 = torch.nn.ModuleList(head_nets3)

    @property
    def head_nets(self):
        return list(self.head_nets1) + list(self.head_nets2) + list(self.head_nets3)

    def io_scales(self):
        return (
            [self.base_net.input_output_scale[0] for _ in self.head_nets1] +
            [self.base_net.input_output_scale[1] for _ in self.head_nets2] +
            [self.base_net.input_output_scale[2] for _ in self.head_nets3]
        )

    def forward(self, x):  # pylint: disable=arguments-differ
        x1, x2, x3 = self.base_net(x)
        h1 = [hn(x1) for hn in self.head_nets1]
        h2 = [hn(x2) for hn in self.head_nets2]
        h3 = [hn(x3) for hn in self.head_nets3]
        return [h for hs in (h1, h2, h3) for h in hs]


def factory(args):
    if args.checkpoint is None and args.basenet is None:
        raise Exception('must specify --checkpoint or --basenet')

    if not args.checkpoint:
        net_cpu = factory_from_scratch(
            args.basenet, args.headnets,
            pretrained=args.pretrain,
            dropout_p=args.dropout,
            quad=args.quad,
        )
        epoch = 0
    else:
        checkpoint = torch.load(args.checkpoint)
        net_cpu = checkpoint['model']
        epoch = checkpoint['epoch']

        # initialize for eval
        net_cpu.eval()
        for head in net_cpu.head_nets:
            head.apply_class_sigmoid = True

        # normalize for backwards compatibility
        for head in net_cpu.head_nets:
            head.shortname = head.shortname.replace('PartsIntensityFields', 'pif')
            head.shortname = head.shortname.replace('PartsAssociationFields', 'paf')
            if not hasattr(head, 'dropout') or head.dropout is None:
                head.dropout = torch.nn.Dropout2d(p=0.0)
            if not hasattr(head, '_quad'):
                if hasattr(head, 'quad'):
                    head._quad = head.quad  # pylint: disable=protected-access
                else:
                    head._quad = 0  # pylint: disable=protected-access
            if not hasattr(head, 'scale_conv'):
                head.scale_conv = None
            if not hasattr(head, 'reg1_spread'):
                head.reg1_spread = None
            if not hasattr(head, 'reg2_spread'):
                head.reg2_spread = None
            if head.shortname == 'pif17' and getattr(head, 'scale_conv') is not None:
                head.shortname = 'pifs17'
            if head._quad == 1 and not hasattr(head, 'dequad_op'):  # pylint: disable=protected-access
                head.dequad_op = torch.nn.PixelShuffle(2)
            if not hasattr(head, 'class_convs') and hasattr(head, 'class_conv'):
                head.class_convs = torch.nn.ModuleList([head.class_conv])

    if args.dilation is not None:
        net_cpu.base_net.atrous0(args.dilation)
        # for head in net_cpu.head_nets:
        #     head.dilation = args.dilation
    if args.dilation_end is not None:
        if args.dilation_end == 1:
            net_cpu.base_net.atrous((1, 1))
        elif args.dilation_end == 2:
            net_cpu.base_net.atrous((1, 2))
        elif args.dilation_end == 4:
            net_cpu.base_net.atrous((2, 4))
        else:
            raise Exception
        # for head in net_cpu.head_nets:
        #     head.dilation = (args.dilation or 1.0) * args.dilation_end

    return net_cpu, epoch


def factory_from_scratch(basename, headnames, *,
                         pretrained=True, dropout_p=0.0, quad=0):
    if 'resnet50' in basename:
        base_vision = torchvision.models.resnet50(pretrained)
    elif 'resnet101' in basename:
        base_vision = torchvision.models.resnet101(pretrained)
    elif 'resnet152' in basename:
        base_vision = torchvision.models.resnet152(pretrained)
    elif 'resnet260' in basename:
        assert pretrained is False
        base_vision = torchvision.models.ResNet(
            torchvision.models.resnet.Bottleneck, [3, 8, 72, 3])
    # elif basename == 'densenet121':
    #     basenet = basenetworks.DenseNet(torchvision.models.densenet121(pretrained), 'DenseNet121')
    # else:
    #     raise Exception('basenet not supported')
    else:
        raise Exception('unknown base network in {}'.format(basename))
    resnet_factory = basenetworks.ResnetBlocks(base_vision)

    # input block
    use_pool = 'pool0' in basename
    conv_stride = 2
    if 'is4' in basename:
        conv_stride = 4
    if 'is1' in basename:
        conv_stride = 1
    pool_stride = 2
    if 'pool0s4' in basename:
        pool_stride = 4

    # all blocks
    blocks = [
        resnet_factory.input_block(use_pool, conv_stride, pool_stride),
        resnet_factory.block2(),
        resnet_factory.block3(),
        resnet_factory.block4(),
    ]
    if 'block5' in basename:
        blocks.append(resnet_factory.block5())

    # downsample
    if 'concat' in basename:
        for b in blocks[2:]:
            resnet_factory.replace_downsample(b)

    def create_headnet(name, n_features):
        if name in ('pif',):
            return heads.CompositeField(17, n_features, shortname='pif',
                                        n_vectors=1, n_scales=1,
                                        dropout_p=dropout_p, quad=quad)
        if name in ('ppif', 'pifb'):
            return heads.PartIntensityFields(17, n_features,
                                             dropout_p=dropout_p, quad=quad)
        if name in ('pifs',):
            return heads.PartIntensityFields(17, n_features,
                                             dropout_p=dropout_p, quad=quad,
                                             with_scale=True)
        if name == 'paf16':
            return heads.PartAssociationFields(16, n_features,
                                               dropout_p=dropout_p, quad=quad)
        if name in ('paf',):
            return heads.CompositeField(19, n_features, shortname='paf',
                                        n_vectors=2, n_scales=0,
                                        dropout_p=dropout_p, quad=quad)
        if name in ('paf19', 'pafb'):
            return heads.PartAssociationFields(19, n_features,
                                               dropout_p=dropout_p, quad=quad)
        if name in ('pafs19',):
            return heads.PartAssociationFields(19, n_features,
                                               dropout_p=dropout_p, quad=quad,
                                               predict_spread=True)
        if name in ('pafs', 'pafs19n2', 'pafsb'):
            return heads.NPartAssociationFields(19, n_features,
                                                dropout_p=dropout_p, quad=quad,
                                                predict_spread=True)
        if name == 'paf44':
            return heads.PartAssociationFields(44, n_features,
                                               dropout_p=dropout_p, quad=quad)
        if name in ('psf'):
            return heads_corr.CompositeField(17,n_features, shortname='psf',
                                        n_vectors=2, n_scales=0,
                                        dropout_p=dropout_p, quad=quad,more= True)
        if name in ('psf_co'):
            return heads_psf.CompositeField(17,n_features, shortname='psf',
                                        n_vectors=2, n_scales=0,
                                        dropout_p=dropout_p, quad=quad,more= True)
        raise Exception('headnet {} not supported'.format(name))

    if 'pifb' in headnames or 'pafb' in headnames:
        basenet = basenetworks.BaseNetwork(
            torch.nn.ModuleList([torch.nn.Sequential(*blocks[:-1]), blocks[-1]]),
            basename,
            [resnet_factory.stride(blocks[:-1]), resnet_factory.stride(blocks)],
            [resnet_factory.out_channels(blocks[-2]), resnet_factory.out_channels(blocks[-1])],
        )
        head1 = [create_headnet(h, basenet.out_features[0])
                 for h in headnames if h.endswith('b')]
        head2 = [create_headnet(h, basenet.out_features[1])
                 for h in headnames if not h.endswith('b')]
        return Shell2Stage(basenet, head1, head2)

    if 'ppif' in headnames:
        # TODO
        head2 = [create_headnet(h, basenet.out_features[1])
                 for h in headnames if h == 'ppif']
        head3 = [create_headnet(h, basenet.out_features[2])
                 for h in headnames if h != 'ppif']
        return ShellFork(basenet, [], head2, head3)

    basenet = basenetworks.BaseNetwork(
        torch.nn.Sequential(*blocks),
        basename,
        resnet_factory.stride(blocks),
        resnet_factory.out_channels(blocks[-1]),
    )
    if 'psf' in headnames :
        headnets = [create_headnet(h, basenet.out_features) for h in headnames if h != 'skeleton']
        return Shell_psf(basenet, headnets)
    else:
        headnets = [create_headnet(h, basenet.out_features) for h in headnames if h != 'skeleton']
        return Shell(basenet, headnets)


def cli(parser):
    group = parser.add_argument_group('network configuration')
    group.add_argument('--checkpoint', default=None,
                       help='load a model from a checkpoint')
    group.add_argument('--dilation', default=None, type=int,
                       help='apply atrous')
    group.add_argument('--dilation-end', default=None, type=int,
                       help='apply atrous')
    group.add_argument('--basenet', default=None,
                       help='base network')
    group.add_argument('--headnets', default=['pifs', 'pafs'], nargs='+',
                       help='head networks')
    group.add_argument('--dropout', default=0.0, type=float,
                       help='zeroing probability of feature in head input')
    group.add_argument('--quad', default=0, type=int,
                       help='number of times to apply quad to heads')
    group.add_argument('--no-pretrain', dest='pretrain', default=True, action='store_false',
                       help='create model without ImageNet pretraining')
