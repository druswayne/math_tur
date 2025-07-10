// Управление множественными изображениями для новостей
let imageIndex = 1;

function addImageUpload() {
    const container = document.getElementById('imageUploads');
    const newItem = document.createElement('div');
    newItem.className = 'image-upload-item mb-3';
    newItem.innerHTML = 
        '<div class="row">' +
            '<div class="col-md-8">' +
                '<input type="file" class="form-control" name="images" accept="image/*">' +
            '</div>' +
            '<div class="col-md-4">' +
                '<input type="text" class="form-control" name="captions" placeholder="Подпись к изображению">' +
            '</div>' +
        '</div>' +
        '<div class="form-check mt-2">' +
            '<input class="form-check-input" type="radio" name="main_image_index" value="' + imageIndex + '" id="main_new_' + imageIndex + '">' +
            '<label class="form-check-label" for="main_new_' + imageIndex + '">' +
                'Главное изображение' +
            '</label>' +
        '</div>' +
        '<button type="button" class="btn btn-outline-danger btn-sm mt-2" onclick="removeImageUpload(this)">' +
            '<i class="bi bi-trash me-2"></i>Удалить' +
        '</button>';
    container.appendChild(newItem);
    imageIndex++;
}

function removeImageUpload(button) {
    button.parentElement.remove();
}

// Предварительный просмотр изображений
function setupImagePreview() {
    const fileInputs = document.querySelectorAll('input[type="file"]');
    const previewContainer = document.getElementById('imagePreview');
    
    fileInputs.forEach(input => {
        input.addEventListener('change', function() {
            if (this.files && this.files[0]) {
                const reader = new FileReader();
                reader.onload = function(e) {
                    if (previewContainer) {
                        // Для страницы добавления новости
                        const img = document.createElement('img');
                        img.src = e.target.result;
                        img.className = 'img-fluid rounded mb-2';
                        img.style.maxHeight = '200px';
                        
                        previewContainer.innerHTML = '';
                        previewContainer.appendChild(img);
                    } else {
                        // Для страницы редактирования новости
                        const container = input.closest('.image-upload-item');
                        let preview = container.querySelector('.image-preview');
                        
                        if (!preview) {
                            preview = document.createElement('div');
                            preview.className = 'image-preview mt-2';
                            container.appendChild(preview);
                        }
                        
                        preview.innerHTML = '<img src="' + e.target.result + '" class="img-thumbnail" style="max-width: 100px; max-height: 100px;">';
                    }
                };
                reader.readAsDataURL(this.files[0]);
            }
        });
    });
}

// Инициализация при загрузке страницы
document.addEventListener('DOMContentLoaded', function() {
    setupImagePreview();
    
    // Устанавливаем начальный индекс для страницы редактирования
    const existingImages = document.querySelectorAll('.existing-image-item');
    if (existingImages.length > 0) {
        imageIndex = existingImages.length + 1;
    }
}); 