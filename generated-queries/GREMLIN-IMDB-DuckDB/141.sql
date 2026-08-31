SELECT count(*)
FROM aka_title, complete_cast, info_type, movie_info, movie_keyword, movie_link, name, person_info, title
WHERE info_type.info = 'LD production country'
  AND aka_title.movie_id = title.id
  AND complete_cast.movie_id = title.id
  AND movie_info.info_type_id = info_type.id
  AND movie_info.movie_id = title.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.linked_movie_id = title.id
  AND person_info.info_type_id = info_type.id
  AND person_info.person_id = name.id;
