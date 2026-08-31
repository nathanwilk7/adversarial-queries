SELECT count(*)
FROM aka_name, complete_cast, info_type, keyword, link_type, movie_info, movie_keyword, movie_link, name, person_info, title
WHERE aka_name.imdb_index = ''
  AND aka_name.person_id = name.id
  AND complete_cast.movie_id = title.id
  AND movie_info.info_type_id = info_type.id
  AND movie_info.movie_id = title.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.link_type_id = link_type.id
  AND movie_link.linked_movie_id = title.id
  AND person_info.info_type_id = info_type.id
  AND person_info.person_id = name.id;
