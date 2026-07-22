import os
import glob
from PIL import Image

def main():
    print("Generating cluster gallery...")
    # Find all NOVEL images in the first session's report
    gallery_dir = "data/production/1368973312/report/saliency_gallery"
    novel_imgs = glob.glob(os.path.join(gallery_dir, "NOVEL_*.png"))
    
    if not novel_imgs:
        print("No NOVEL images found. Looking for any saliency maps...")
        novel_imgs = glob.glob(os.path.join(gallery_dir, "*.png"))[:4]
    else:
        # Sort or just take up to 4 images
        novel_imgs = novel_imgs[:4]
        
    if not novel_imgs:
        print("No images found to generate gallery.")
        return
        
    print(f"Found {len(novel_imgs)} images for gallery.")
    
    images = [Image.open(img) for img in novel_imgs]
    
    # Assuming all images are the same size
    widths, heights = zip(*(i.size for i in images))
    max_width = max(widths)
    total_height = sum(heights)
    
    # Create a new blank image
    new_im = Image.new('RGB', (max_width, total_height))
    
    y_offset = 0
    for im in images:
        new_im.paste(im, (0, y_offset))
        y_offset += im.size[1]
        
    out_path = "paper_draft/springer/img/fig_cluster_gallery.png"
    new_im.save(out_path)
    print(f"Saved gallery to {out_path}")

if __name__ == '__main__':
    main()
