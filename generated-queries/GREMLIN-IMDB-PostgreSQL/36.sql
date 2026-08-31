SELECT count(*)
FROM aka_title, link_type, movie_info, movie_info_idx, movie_keyword, movie_link, title
WHERE aka_title.production_year = 2009
  AND aka_title.movie_id = title.id
  AND movie_info.movie_id = title.id
  AND movie_info_idx.movie_id = title.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.link_type_id = link_type.id
  AND movie_link.linked_movie_id = title.id;
