from django.db import models


class Author(models.Model):
    name = models.CharField(max_length=200)
    email = models.EmailField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = 'tests_ours'


class Book(models.Model):
    title = models.CharField(max_length=200)
    author = models.ForeignKey(Author, on_delete=models.CASCADE, related_name='books')
    published = models.DateField(null=True)
    tags = models.ManyToManyField('Tag', blank=True)

    class Meta:
        app_label = 'tests_ours'


class Tag(models.Model):
    name = models.CharField(max_length=50, unique=True)

    class Meta:
        app_label = 'tests_ours'
