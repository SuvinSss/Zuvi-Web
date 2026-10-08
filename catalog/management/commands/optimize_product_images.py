from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from catalog.models import Product, ProductImage
from catalog.image_processing import display_image

class Command(BaseCommand):
    help='Generate missing optimized PNG display images, retaining every original.'
    def add_arguments(self, parser):
        parser.add_argument('--limit',type=int,default=100)
    def handle(self,*args,**options):
        if options['limit'] < 1:
            raise CommandError('Limit must be positive')
        ids=list(ProductImage.objects.filter(display_image='').order_by('pk').values_list('pk','product_id')[:options['limit']])
        done=0
        for image_id, product_id in ids:
            with transaction.atomic():
                # Serialize with the same parent lock used by image replacement.
                Product.objects.select_for_update().get(pk=product_id)
                image=ProductImage.objects.filter(pk=image_id,display_image='').first()
                if image is None:
                    continue
                image.image.open('rb')
                try:
                    image.display_image=display_image(image.image)
                    image.save(update_fields=['display_image'])
                    done+=1
                finally:
                    image.image.close()
        self.stdout.write(f'Optimized {done} images; originals preserved.')
